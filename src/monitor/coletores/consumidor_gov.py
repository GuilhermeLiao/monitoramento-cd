"""Indicadores do ano corrente no Consumidor.gov.br (aba "2026" do perfil da empresa).

A página de perfil traz um token de sessão na chamada `selecionarAba('ANOS', <ano>, '<token>')`;
com ele, o próprio site busca os indicadores em JSON. O token só vale na sessão (cookies)
que abriu a página, por isso as duas requisições usam o mesmo cliente e são repetidas
juntas em caso de falha.
"""

import logging
import math
import random
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
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
from monitor.coletores.tentativas import ErroTransitorio, com_retentativas
from monitor.settings import FUSO_REFERENCIA

log = logging.getLogger(__name__)

URL_BASE = "https://www.consumidor.gov.br"
TIMEOUT_SEGUNDOS = 30.0
PAUSA_ENTRE_EMPRESAS_SEGUNDOS = (1.0, 2.0)
CABECALHOS = {"User-Agent": "Mozilla/5.0 (monitoramento-cd; coleta semanal de indicadores)"}
_ABA_ANUAL = re.compile(r"selecionarAba\(\s*'ANOS'\s*,\s*(\d{4})\s*,\s*'([^']+)'")

Dormir = Callable[[float], None]
Sortear = Callable[[float, float], float]


class EmpresaNaoEncontrada(LookupError):
    pass


class DadosInvalidos(ValueError):
    """O site respondeu, mas fora do formato esperado (provável mudança no site)."""


def _id_valido(identificador: str) -> bool:
    return identificador.isascii() and identificador.isdigit()


def _numero(dados: dict[str, Any], campo: str, minimo: float, maximo: float) -> Decimal | None:
    """Valor do indicador ou None quando o site mostra "S/R" (sem registros)."""
    if campo not in dados:
        raise DadosInvalidos(f"campo {campo!r} ausente na resposta")
    valor = dados[campo]
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int | float) or not math.isfinite(valor):
        raise DadosInvalidos(f"{campo} inválido: {valor!r}")
    if not minimo <= valor <= maximo:
        raise DadosInvalidos(f"{campo} fora da faixa de {minimo} a {maximo}: {valor}")
    return Decimal(str(valor))


def metricas_do_ano(dados: dict[str, Any], ano: int, hoje: date) -> list[RegistroMetrica]:
    total = dados.get("totalReclamacoes")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise DadosInvalidos(f"totalReclamacoes ausente ou inválido: {total!r}")
    valores = {
        "total_reclamacoes": total,
        "pct_resolvidas": _numero(dados, "indicadorSolucao", 0, 100),
        "nota_consumidor": _numero(dados, "indicadorSatisfacaoAtendimento", 1, 5),
        "pct_respondidas": _numero(dados, "indicadorReclamcoesRespondidas", 0, 100),
        "tempo_resposta_dias": _numero(dados, "indicadorPrazoMedioRespostas", 0, 365),
    }
    inicio = date(ano, 1, 1)
    return [
        RegistroMetrica(codigo, valor, periodo_inicio=inicio, periodo_fim=hoje)
        for codigo, valor in valores.items()
    ]


@registrar
class ConsumidorGovColetor(Coletor):
    nome = "consumidor_gov"
    plataforma = "consumidor_gov"

    def __init__(
        self,
        cliente: httpx.Client | None = None,
        dormir: Dormir = time.sleep,
        sortear: Sortear = random.uniform,
        hoje: Callable[[], date] = lambda: datetime.now(FUSO_REFERENCIA).date(),
    ) -> None:
        self._cliente = cliente or httpx.Client(
            base_url=URL_BASE, timeout=TIMEOUT_SEGUNDOS, headers=CABECALHOS, follow_redirects=True
        )
        self._dormir = dormir
        self._sortear = sortear
        self._hoje = hoje
        self._primeira = True

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        identificador = perfil.identificador
        if not _id_valido(identificador):
            raise ValueError(
                "identificador do consumidor.gov deve ser o número da URL do perfil "
                f"(/pages/empresa/<número>/perfil): {identificador!r}"
            )
        if not self._primeira:
            self._dormir(self._sortear(*PAUSA_ENTRE_EMPRESAS_SEGUNDOS))
        self._primeira = False

        ano, dados = com_retentativas(
            lambda: self._buscar(identificador), dormir=self._dormir, sortear=self._sortear
        )
        return ResultadoColeta(
            metricas=metricas_do_ano(dados, ano, self._hoje()),
            respostas_brutas=[
                RespostaBrutaColetada(
                    f"{URL_BASE}/pages/empresa/{identificador}/perfil#ANOS_{ano}", dados
                )
            ],
        )

    def _get(self, url: str) -> httpx.Response:
        try:
            resposta = self._cliente.get(url)
        except httpx.TransportError as erro:
            raise ErroTransitorio(f"falha de rede no consumidor.gov: {erro!r}") from erro
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise ErroTransitorio(f"consumidor.gov respondeu HTTP {resposta.status_code}")
        resposta.raise_for_status()
        return resposta

    def _buscar(self, identificador: str) -> tuple[int, dict[str, Any]]:
        pagina = self._get(f"/pages/empresa/{identificador}/perfil")
        achado = _ABA_ANUAL.search(pagina.text)
        if not achado:
            raise EmpresaNaoEncontrada(
                f"perfil {identificador} sem a aba do ano: a empresa não existe no "
                "consumidor.gov ou a página mudou"
            )
        ano, token = int(achado.group(1)), achado.group(2)
        resposta = self._get(f"/pages/empresa/{token}/aba/ANUAL/periodo/998/perfil.json")
        try:
            dados = resposta.json()
        except ValueError as erro:
            raise DadosInvalidos("indicadores do consumidor.gov não vieram em JSON") from erro
        if not isinstance(dados, dict):
            raise DadosInvalidos(f"resposta inesperada: {type(dados).__name__}")
        return ano, dados
