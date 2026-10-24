"""Instagram pela Graph API (Business Discovery): seguidores e posts do último mês inteiro.

Consulta perfis profissionais de terceiros a partir da conta profissional do dono
(IG_USER_ID), com um token de Página da Meta (META_ACCESS_TOKEN). O token vai no
cabeçalho Authorization, nunca na URL, para não aparecer em mensagens de erro.
"""

import json
import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from monitor.coletores import registrar
from monitor.coletores.base import (
    Coletor,
    PerfilAlvo,
    RegistroMetrica,
    RespostaBrutaColetada,
    ResultadoColeta,
)
from monitor.coletores.tentativas import ErroTransitorio, com_retentativas
from monitor.db.models import PostInstagram, SnapshotPostInstagram
from monitor.settings import FUSO_REFERENCIA, get_settings

log = logging.getLogger(__name__)

URL_BASE = "https://graph.facebook.com"
TIMEOUT_SEGUNDOS = 30.0
CAMPOS_POST = "id,timestamp,like_count,comments_count,media_type,permalink"
POSTS_POR_PAGINA = 50
MAX_PAGINAS = 20
# Posts fixados aparecem no topo fora da ordem de data (no máximo 3 por perfil):
# só para de paginar depois de ver mais posts antigos seguidos do que isso.
ANTIGOS_SEGUIDOS_PARA_PARAR = 4
PAUSA_ENTRE_PERFIS_SEGUNDOS = (1.0, 2.0)
USO_PARA_DESACELERAR = 75
ESPERA_USO_ALTO_SEGUNDOS = 60.0
DIAS_AVISO_TOKEN = 10
# Códigos de limite de uso e instabilidade da Graph API: vale tentar de novo.
CODIGOS_TRANSITORIOS = {1, 2, 4, 17, 32, 341, 613, 80001, 80002}
_USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")

Dormir = Callable[[float], None]
Sortear = Callable[[float, float], float]


class ConfiguracaoAusente(RuntimeError):
    pass


class TokenInvalido(RuntimeError):
    pass


class PerfilIndisponivel(LookupError):
    pass


class ErroGraphApi(RuntimeError):
    pass


class DadosInvalidos(ValueError):
    pass


@dataclass(frozen=True)
class PostColetado:
    media_id: str
    publicado_em: datetime
    tipo_midia: str | None
    permalink: str | None
    curtidas: int | None
    comentarios: int | None


def ultimo_mes_inteiro(hoje: date) -> tuple[date, date]:
    fim = hoje.replace(day=1) - timedelta(days=1)
    return fim.replace(day=1), fim


def _contagem(valor: Any) -> int | None:
    """Contagem da API; ausente (curtidas ocultas) vira None, nunca zero."""
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise DadosInvalidos(f"contagem inválida: {valor!r}")
    return valor


def _uso_maximo(cabecalhos: httpx.Headers) -> float:
    """Maior percentual de uso informado em X-App-Usage e X-Business-Use-Case-Usage."""
    valores: list[float] = []
    for nome in ("x-app-usage", "x-business-use-case-usage"):
        bruto = cabecalhos.get(nome)
        if not bruto:
            continue
        try:
            dados = json.loads(bruto)
        except ValueError:
            continue
        blocos = [dados] if nome == "x-app-usage" else [b for lista in dados.values() for b in lista]
        for bloco in blocos:
            valores += [
                float(bloco[c])
                for c in ("call_count", "total_cputime", "total_time")
                if isinstance(bloco.get(c), int | float)
            ]
    return max(valores, default=0.0)


@registrar
class InstagramColetor(Coletor):
    nome = "instagram"
    plataforma = "instagram"

    def __init__(
        self,
        cliente: httpx.Client | None = None,
        token: str | None = None,
        ig_user_id: str | None = None,
        versao: str | None = None,
        dormir: Dormir = time.sleep,
        sortear: Sortear = random.uniform,
        hoje: Callable[[], date] = lambda: datetime.now(FUSO_REFERENCIA).date(),
        agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if token is None or ig_user_id is None or versao is None:
            settings = get_settings()
            token = token or settings.meta_access_token
            ig_user_id = ig_user_id or settings.ig_user_id
            versao = versao or settings.meta_graph_api_version
        if not token or not ig_user_id:
            raise ConfiguracaoAusente(
                "defina META_ACCESS_TOKEN e IG_USER_ID (no .env ou nos Secrets do GitHub)"
            )
        self._token = token.strip()
        self._ig = ig_user_id.strip()
        self._versao = versao
        self._cliente = cliente or httpx.Client(base_url=URL_BASE, timeout=TIMEOUT_SEGUNDOS)
        self._dormir = dormir
        self._sortear = sortear
        self._hoje = hoje
        self._agora = agora
        self._primeiro = True
        self.avisos: list[str] = []

    # ------------------------------------------------------------- token

    def preparar(self, perfis: list[PerfilAlvo]) -> None:
        self.verificar_token()

    def verificar_token(self) -> None:
        """Avisa (sem interromper) quando o token ou o acesso a dados está perto de vencer."""
        try:
            resposta = self._cliente.get(
                f"/{self._versao}/debug_token",
                params={"input_token": self._token},
                headers=self._cabecalhos(),
            )
            dados = resposta.json().get("data") or {}
        except (httpx.HTTPError, ValueError) as erro:
            self.avisos.append(f"não foi possível verificar o token da Meta ({type(erro).__name__})")
            return
        if not dados.get("is_valid", False):
            self.avisos.append(
                "token da Meta inválido ou expirado: gere um novo (README, seção Instagram)"
            )
            return
        agora = self._agora()
        for campo, descricao in (
            ("expires_at", "O token da Meta expira"),
            ("data_access_expires_at", "O acesso a dados do token da Meta expira"),
        ):
            instante = dados.get(campo)
            if not instante:  # 0 ou ausente: não expira
                continue
            vence = datetime.fromtimestamp(instante, UTC)
            dias = (vence - agora).days
            if dias <= DIAS_AVISO_TOKEN:
                self.avisos.append(
                    f"{descricao} em {dias} dia(s) ({vence:%d/%m/%Y}): renove pelo passo a passo "
                    "do README, seção Instagram"
                )

    # ------------------------------------------------------------- coleta

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        username = perfil.identificador.strip().lstrip("@")
        if not _USERNAME.fullmatch(username):
            raise ValueError(f"username do Instagram inválido: {perfil.identificador!r}")
        if not self._primeiro:
            self._dormir(self._sortear(*PAUSA_ENTRE_PERFIS_SEGUNDOS))
        self._primeiro = False

        inicio, fim = ultimo_mes_inteiro(self._hoje())
        seguidores: int | None = None
        total_publicacoes: int | None = None
        posts: list[PostColetado] = []
        cursor: str | None = None
        antigos_seguidos = 0
        for _ in range(MAX_PAGINAS):
            perfil_api = self._business_discovery(username, cursor)
            if seguidores is None:
                seguidores = _contagem(perfil_api.get("followers_count"))
                total_publicacoes = _contagem(perfil_api.get("media_count"))
                if seguidores is None:
                    raise DadosInvalidos(f"@{username}: followers_count ausente na resposta")
            midia = perfil_api.get("media") or {}
            lote = midia.get("data") or []
            for item in lote:
                post = self._post(item)
                dia = post.publicado_em.astimezone(FUSO_REFERENCIA).date()
                if dia < inicio:
                    antigos_seguidos += 1
                    continue
                antigos_seguidos = 0
                if dia <= fim:
                    posts.append(post)
            if antigos_seguidos >= ANTIGOS_SEGUIDOS_PARA_PARAR:
                break
            cursor = ((midia.get("paging") or {}).get("cursors") or {}).get("after")
            if not lote or not cursor:
                break
        else:
            log.warning(
                "limite de paginas atingido antes do inicio do mes",
                extra={"username": username, "paginas": MAX_PAGINAS},
            )

        return ResultadoColeta(
            metricas=[
                RegistroMetrica("seguidores", seguidores),
                RegistroMetrica("posts_periodo", len(posts), periodo_inicio=inicio, periodo_fim=fim),
            ],
            respostas_brutas=[
                RespostaBrutaColetada(
                    f"{URL_BASE}/{self._versao}/business_discovery/{username}",
                    {
                        "followers_count": seguidores,
                        "media_count": total_publicacoes,
                        "periodo": [inicio.isoformat(), fim.isoformat()],
                        "posts": [
                            {"id": p.media_id, "timestamp": p.publicado_em.isoformat(),
                             "like_count": p.curtidas, "comments_count": p.comentarios}
                            for p in posts
                        ],
                    },
                )
            ],
            registros=posts,
        )

    @staticmethod
    def _post(item: dict[str, Any]) -> PostColetado:
        try:
            publicado = datetime.strptime(item["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
            media_id = str(item["id"])
        except (KeyError, TypeError, ValueError) as erro:
            raise DadosInvalidos(f"post sem id ou data válidos: {item!r}"[:300]) from erro
        return PostColetado(
            media_id=media_id,
            publicado_em=publicado,
            tipo_midia=item.get("media_type"),
            permalink=item.get("permalink"),
            curtidas=_contagem(item.get("like_count")),
            comentarios=_contagem(item.get("comments_count")),
        )

    def _cabecalhos(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _business_discovery(self, username: str, cursor: str | None) -> dict[str, Any]:
        pagina = f".after({cursor})" if cursor else ""
        campos = (
            f"business_discovery.username({username})"
            f"{{followers_count,media_count,media.limit({POSTS_POR_PAGINA}){pagina}{{{CAMPOS_POST}}}}}"
        )

        def tentativa() -> dict[str, Any]:
            try:
                resposta = self._cliente.get(
                    f"/{self._versao}/{self._ig}",
                    params={"fields": campos},
                    headers=self._cabecalhos(),
                )
            except httpx.TransportError as erro:
                raise ErroTransitorio(f"falha de rede na Graph API: {type(erro).__name__}") from erro
            uso = _uso_maximo(resposta.headers)
            if uso >= USO_PARA_DESACELERAR:
                log.warning("uso alto da Graph API, desacelerando", extra={"uso_pct": uso})
                self._dormir(ESPERA_USO_ALTO_SEGUNDOS)
            try:
                corpo = resposta.json()
            except ValueError:
                corpo = {}
            erro = corpo.get("error") if isinstance(corpo, dict) else None
            if erro:
                self._levantar(erro, username, resposta.status_code)
            if resposta.status_code == 429 or resposta.status_code >= 500:
                raise ErroTransitorio(f"Graph API respondeu HTTP {resposta.status_code}")
            if resposta.status_code >= 400:
                raise ErroGraphApi(f"Graph API respondeu HTTP {resposta.status_code}")
            dados = corpo.get("business_discovery")
            if not isinstance(dados, dict):
                raise DadosInvalidos(f"@{username}: resposta sem business_discovery")
            return dados

        return com_retentativas(tentativa, dormir=self._dormir, sortear=self._sortear)

    @staticmethod
    def _levantar(erro: dict[str, Any], username: str, status: int) -> None:
        codigo = erro.get("code")
        subcodigo = erro.get("error_subcode")
        mensagem = str(erro.get("message", ""))[:300]
        if codigo in CODIGOS_TRANSITORIOS or erro.get("is_transient") or status >= 500:
            raise ErroTransitorio(f"Graph API ({codigo}): {mensagem}")
        if codigo == 190:
            raise TokenInvalido(
                f"token da Meta inválido ou expirado ({mensagem}): gere um novo (README, Instagram)"
            )
        if codigo == 110 or subcodigo == 2207013 or "cannot find user" in mensagem.lower():
            raise PerfilIndisponivel(
                f"@{username} não encontrado ou não é uma conta profissional (Business ou Creator)"
            )
        raise ErroGraphApi(f"Graph API ({codigo}/{subcodigo}): {mensagem}")

    # ------------------------------------------------------------- gravação

    def gravar_registros(
        self, sessao: Session, execucao_id: int, perfil: PerfilAlvo, registros: list[Any]
    ) -> None:
        if not registros:
            return
        hoje = self._hoje()
        comando = insert(PostInstagram).values(
            [
                {
                    "perfil_id": perfil.id,
                    "media_id": p.media_id,
                    "publicado_em": p.publicado_em,
                    "tipo_midia": p.tipo_midia,
                    "permalink": p.permalink,
                }
                for p in registros
            ]
        )
        sessao.execute(
            comando.on_conflict_do_update(
                index_elements=["media_id"],
                set_={c: comando.excluded[c] for c in ("tipo_midia", "permalink")},
            )
        )
        ids = {
            media_id: post_id
            for media_id, post_id in sessao.execute(
                select(PostInstagram.media_id, PostInstagram.id).where(
                    PostInstagram.media_id.in_([p.media_id for p in registros])
                )
            )
        }
        snapshots = insert(SnapshotPostInstagram).values(
            [
                {
                    "post_id": ids[p.media_id],
                    "execucao_id": execucao_id,
                    "data_coleta": hoje,
                    "curtidas": p.curtidas,
                    "curtidas_ocultas": p.curtidas is None,
                    "comentarios": p.comentarios,
                    "idade_post_dias": (hoje - p.publicado_em.astimezone(FUSO_REFERENCIA).date()).days,
                }
                for p in registros
            ]
        )
        sessao.execute(
            snapshots.on_conflict_do_update(
                constraint="uq_snapshots_posts_instagram_post_data",
                set_={
                    c: snapshots.excluded[c]
                    for c in ("execucao_id", "curtidas", "curtidas_ocultas", "comentarios",
                              "idade_post_dias")
                },
            )
        )
