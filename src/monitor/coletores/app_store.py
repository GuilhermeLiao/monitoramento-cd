"""Nota média dos apps na App Store do Brasil, pela API pública iTunes Lookup."""

import logging
import random
import time
from itertools import batched
from typing import Any

import httpx

from monitor.coletores import registrar
from monitor.coletores.base import (
    Coletor,
    PerfilAlvo,
    RegistroMetrica,
    RespostaBrutaColetada,
    ResultadoColeta,
)
from monitor.coletores.lojas import (
    TIMEOUT_SEGUNDOS,
    AppNaoEncontrado,
    Dormir,
    Sortear,
    nota_validada,
    pausar_entre_apps,
)
from monitor.coletores.tentativas import ErroTransitorio, com_retentativas

log = logging.getLogger(__name__)

URL_LOOKUP = "https://itunes.apple.com/lookup"
PAIS = "br"
TAMANHO_LOTE = 50
# Só o necessário para conferir a nota depois; descrição e imagens ficam de fora (espaço).
CAMPOS_BRUTOS = (
    "trackId",
    "trackName",
    "bundleId",
    "averageUserRating",
    "userRatingCount",
    "averageUserRatingForCurrentVersion",
    "userRatingCountForCurrentVersion",
    "version",
    "currentVersionReleaseDate",
)


def _id_valido(identificador: str) -> bool:
    return identificador.isascii() and identificador.isdigit()


@registrar
class AppStoreColetor(Coletor):
    nome = "app_store"
    plataforma = "app_store"

    def __init__(
        self,
        cliente: httpx.Client | None = None,
        dormir: Dormir = time.sleep,
        sortear: Sortear = random.uniform,
    ) -> None:
        self._cliente = cliente or httpx.Client(timeout=TIMEOUT_SEGUNDOS)
        self._dormir = dormir
        self._sortear = sortear
        # Resultado dos lotes já consultados, por ID: o app, None (não veio) ou o erro do lote.
        self._consultados: dict[str, dict[str, Any] | Exception | None] = {}

    def preparar(self, perfis: list[PerfilAlvo]) -> None:
        ids = [p.identificador for p in perfis if _id_valido(p.identificador)]
        for indice, lote in enumerate(batched(ids, TAMANHO_LOTE)):
            if indice:
                pausar_entre_apps(self._dormir, self._sortear)
            self._consultar(lote)

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        identificador = perfil.identificador
        if not _id_valido(identificador):
            raise ValueError(
                f"identificador da App Store deve ser o ID numérico do app: {identificador!r}"
            )
        if identificador not in self._consultados:
            self._consultar((identificador,))
        app = self._consultados[identificador]
        if isinstance(app, Exception):
            raise app
        if app is None:
            raise AppNaoEncontrado(
                f"app {identificador} não veio no iTunes Lookup: pode ter sido removido "
                "ou não existir na loja do Brasil"
            )
        nota = nota_validada(app.get("averageUserRating"), app.get("userRatingCount"))
        return ResultadoColeta(
            metricas=[RegistroMetrica("nota_media", nota)],
            respostas_brutas=[
                RespostaBrutaColetada(
                    f"{URL_LOOKUP}?id={identificador}&country={PAIS}",
                    {campo: app[campo] for campo in CAMPOS_BRUTOS if campo in app},
                )
            ],
        )

    def _consultar(self, lote: tuple[str, ...]) -> None:
        try:
            apps = self._buscar(lote)
        except Exception as erro:  # noqa: BLE001 - a falha do lote vira erro de cada perfil dele
            log.warning("falha no lote do iTunes Lookup", extra={"ids": len(lote)})
            self._consultados.update(dict.fromkeys(lote, erro))
            return
        self._consultados.update({identificador: apps.get(identificador) for identificador in lote})

    def _buscar(self, lote: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        def tentativa() -> dict[str, Any]:
            try:
                resposta = self._cliente.get(
                    URL_LOOKUP, params={"id": ",".join(lote), "country": PAIS}
                )
            except httpx.TransportError as erro:
                raise ErroTransitorio(f"falha de rede no iTunes Lookup: {erro!r}") from erro
            # A Apple responde 403 quando limita a taxa de chamadas.
            if resposta.status_code in (403, 429) or resposta.status_code >= 500:
                raise ErroTransitorio(f"iTunes Lookup respondeu HTTP {resposta.status_code}")
            resposta.raise_for_status()
            return resposta.json()

        dados = com_retentativas(tentativa, dormir=self._dormir, sortear=self._sortear)
        return {str(app["trackId"]): app for app in dados.get("results", []) if "trackId" in app}
