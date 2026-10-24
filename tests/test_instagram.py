"""Coletor do Instagram, sem rede: respostas da Graph API simuladas."""

import json
from datetime import UTC, date, datetime
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy import func, select, text

from monitor.coletores.base import PerfilAlvo
from monitor.coletores.executor import executar_coletor
from monitor.coletores.instagram import (
    URL_BASE,
    ConfiguracaoAusente,
    InstagramColetor,
    PerfilIndisponivel,
    TokenInvalido,
    ultimo_mes_inteiro,
)
from monitor.coletores.tentativas import ErroTransitorio
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo
from monitor.db.models import PostInstagram, SnapshotPostInstagram

TOKEN = "EAAsegredo123"
IG = "17841421153777986"
HOJE = date(2026, 10, 24)  # último mês inteiro: setembro/2026


def _post(media_id: str, timestamp: str, curtidas: int | None = 10, comentarios: int = 1) -> dict:
    post = {"id": media_id, "timestamp": timestamp, "comments_count": comentarios,
            "media_type": "IMAGE", "permalink": f"https://www.instagram.com/p/{media_id}/"}
    if curtidas is not None:
        post["like_count"] = curtidas
    return post


def _pagina(posts: list[dict], after: str | None = None, seguidores: int = 1000) -> dict:
    media: dict = {"data": posts}
    if after:
        media["paging"] = {"cursors": {"after": after}}
    return {"business_discovery": {"followers_count": seguidores, "media_count": 500,
                                   "media": media, "id": "1"}, "id": IG}


class Relogio:
    def __init__(self):
        self.esperas: list[float] = []

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)

    @staticmethod
    def sortear(minimo: float, maximo: float) -> float:
        return maximo


def _coletor(respostas, relogio=None, hoje=HOJE):
    """`respostas`: uma por requisição; int vira status sem corpo, tupla = (status, corpo[, cabeçalhos])."""
    relogio = relogio or Relogio()
    fila = list(respostas)
    chamadas: list[httpx.Request] = []

    def atender(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao)
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        if isinstance(resposta, int):
            return httpx.Response(resposta)
        if isinstance(resposta, tuple):
            status, corpo, *resto = resposta
            return httpx.Response(status, json=corpo, headers=resto[0] if resto else None)
        return httpx.Response(200, json=resposta)

    coletor = InstagramColetor(
        cliente=httpx.Client(base_url=URL_BASE, transport=httpx.MockTransport(atender)),
        token=TOKEN,
        ig_user_id=IG,
        versao="v26.0",
        dormir=relogio.dormir,
        sortear=relogio.sortear,
        hoje=lambda: hoje,
        agora=lambda: datetime(2026, 10, 24, 12, tzinfo=UTC),
    )
    return coletor, chamadas, relogio


def _perfil(username: str = "nubank", id_: int = 1) -> PerfilAlvo:
    return PerfilAlvo(id=id_, instituicao_id=1, plataforma_codigo="instagram", identificador=username)


def _valores(resultado) -> dict:
    return {m.metrica_codigo: m.valor for m in resultado.metricas}


def test_ultimo_mes_inteiro():
    assert ultimo_mes_inteiro(date(2026, 10, 24)) == (date(2026, 9, 1), date(2026, 9, 30))
    assert ultimo_mes_inteiro(date(2026, 1, 1)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert ultimo_mes_inteiro(date(2024, 3, 15)) == (date(2024, 2, 1), date(2024, 2, 29))


def test_pagina_ate_o_inicio_do_mes_e_pega_so_os_posts_do_mes():
    pagina1 = _pagina(
        [
            _post("fixado", "2025-01-10T12:00:00+0000"),  # fixado no topo, antigo
            _post("outubro", "2026-10-20T19:09:17+0000"),
            # 01/10 00:30 UTC ainda é 30/09 em Brasília: entra no mês.
            _post("fim_set", "2026-10-01T00:30:00+0000", curtidas=None),
            _post("meio_set", "2026-09-15T10:00:00+0000", curtidas=500),
        ],
        after="CURSOR1",
    )
    pagina2 = _pagina(
        [
            _post("inicio_set", "2026-09-01T03:00:00+0000", curtidas=7),
            _post("ago1", "2026-08-31T20:00:00+0000"),
            _post("ago2", "2026-08-30T20:00:00+0000"),
            _post("ago3", "2026-08-29T20:00:00+0000"),
            _post("ago4", "2026-08-28T20:00:00+0000"),
        ],
        after="CURSOR2",
    )
    coletor, chamadas, _ = _coletor([pagina1, pagina2])
    resultado = coletor.coletar(_perfil())

    assert _valores(resultado) == {"seguidores": 1000, "posts_periodo": 3}
    (posts_periodo,) = [m for m in resultado.metricas if m.metrica_codigo == "posts_periodo"]
    assert (posts_periodo.periodo_inicio, posts_periodo.periodo_fim) == (
        date(2026, 9, 1), date(2026, 9, 30))
    assert [(p.media_id, p.curtidas) for p in resultado.registros] == [
        ("fim_set", None), ("meio_set", 500), ("inicio_set", 7)]
    # Parou depois de 4 posts antigos seguidos, sem pedir a terceira página.
    assert len(chamadas) == 2
    assert ".after(CURSOR1)" in unquote(str(chamadas[1].url))


def test_token_vai_no_cabecalho_nunca_na_url():
    coletor, chamadas, _ = _coletor([_pagina([])])
    coletor.coletar(_perfil())
    assert chamadas[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(chamadas[0].url)
    assert "business_discovery.username(nubank)" in unquote(str(chamadas[0].url))


def test_curtidas_ocultas_nunca_viram_zero():
    coletor, _, _ = _coletor([_pagina([_post("a", "2026-09-10T12:00:00+0000", curtidas=None)])])
    (post,) = coletor.coletar(_perfil()).registros
    assert post.curtidas is None


def test_perfil_nao_profissional():
    erro = {"error": {"message": "Invalid user id", "type": "OAuthException", "code": 110,
                      "error_subcode": 2207013}}
    coletor, chamadas, _ = _coletor([(400, erro)])
    with pytest.raises(PerfilIndisponivel, match="@nubank"):
        coletor.coletar(_perfil())
    assert len(chamadas) == 1


def test_token_invalido():
    erro = {"error": {"message": "Error validating access token", "type": "OAuthException",
                      "code": 190}}
    coletor, _, _ = _coletor([(400, erro)])
    with pytest.raises(TokenInvalido, match="README"):
        coletor.coletar(_perfil())


def test_limite_de_uso_tenta_de_novo():
    limite = {"error": {"message": "Application request limit reached", "code": 4}}
    coletor, chamadas, relogio = _coletor([(400, limite), _pagina([])])
    assert _valores(coletor.coletar(_perfil()))["seguidores"] == 1000
    assert len(chamadas) == 2
    assert relogio.esperas == [2.0]


def test_desiste_na_terceira_falha_sem_vazar_o_token():
    coletor, chamadas, _ = _coletor([500, 500, 500])
    with pytest.raises(ErroTransitorio) as erro:
        coletor.coletar(_perfil())
    assert TOKEN not in str(erro.value)
    assert len(chamadas) == 3


def test_uso_alto_desacelera():
    cabecalhos = {"x-app-usage": json.dumps({"call_count": 80, "total_cputime": 5, "total_time": 5})}
    coletor, _, relogio = _coletor([(200, _pagina([]), cabecalhos)])
    coletor.coletar(_perfil())
    assert relogio.esperas == [60.0]


def test_pausa_entre_perfis_e_username_invalido():
    coletor, chamadas, relogio = _coletor([_pagina([]), _pagina([])])
    coletor.coletar(_perfil("nubank", 1))
    coletor.coletar(_perfil("@itau", 2))
    assert relogio.esperas == [2.0]
    assert "username(itau)" in unquote(str(chamadas[1].url))
    with pytest.raises(ValueError, match="inválido"):
        coletor.coletar(_perfil("nome com espaço", 3))


def test_aviso_quando_acesso_a_dados_esta_perto_de_vencer():
    vence = int(datetime(2026, 10, 29, tzinfo=UTC).timestamp())
    debug = {"data": {"is_valid": True, "expires_at": 0, "data_access_expires_at": vence}}
    coletor, _, _ = _coletor([debug])
    coletor.preparar([])
    (aviso,) = coletor.avisos
    assert "acesso a dados" in aviso and "4 dia(s)" in aviso


def test_sem_aviso_quando_token_esta_longe_de_vencer():
    vence = int(datetime(2027, 1, 22, tzinfo=UTC).timestamp())
    debug = {"data": {"is_valid": True, "expires_at": 0, "data_access_expires_at": vence}}
    coletor, _, _ = _coletor([debug])
    coletor.preparar([])
    assert coletor.avisos == []


def test_aviso_quando_token_invalido():
    coletor, _, _ = _coletor([{"data": {"is_valid": False}}])
    coletor.preparar([])
    assert "inválido" in coletor.avisos[0]


def test_sem_credenciais(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@localhost/z")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("IG_USER_ID", "")
    with pytest.raises(ConfiguracaoAusente):
        InstagramColetor()


# ----------------------------------------------------------------------- banco


def test_grava_posts_e_snapshots_de_forma_idempotente(fabrica):
    config = [{"nome": "Banco Exemplo", "nome_curto": "exemplo",
               "perfis": {"instagram": [{"identificador": "nubank"}]}}]
    with fabrica.begin() as sessao:
        repo.sincronizar_config(sessao, validar_config(config))
    debug = {"data": {"is_valid": True, "expires_at": 0, "data_access_expires_at": 0}}
    pagina = _pagina([_post("a", "2026-09-10T12:00:00+0000", curtidas=None),
                      _post("b", "2026-09-20T12:00:00+0000", curtidas=42)])

    for _ in range(2):
        coletor, _, _ = _coletor([debug, pagina])
        resultado = executar_coletor(coletor, fabrica)
        assert (resultado.status, resultado.perfis_ok) == ("sucesso", 1)

    with fabrica() as sessao:
        assert sessao.scalar(select(func.count()).select_from(PostInstagram)) == 2
        snapshots = sessao.execute(
            select(PostInstagram.media_id, SnapshotPostInstagram.curtidas,
                   SnapshotPostInstagram.curtidas_ocultas, SnapshotPostInstagram.idade_post_dias)
            .join(PostInstagram, PostInstagram.id == SnapshotPostInstagram.post_id)
            .order_by(PostInstagram.media_id)
        ).all()
        metricas = dict(sessao.execute(text(
            "SELECT metrica_codigo, valor FROM vw_metricas_atuais WHERE plataforma_codigo = 'instagram'"
        )).all())
        view = sessao.execute(text(
            "SELECT media_id, data_publicacao, mes_publicacao, curtidas FROM vw_instagram_posts "
            "ORDER BY media_id"
        )).all()
    assert [tuple(s) for s in snapshots] == [("a", None, True, 44), ("b", 42, False, 34)]
    assert metricas == {"seguidores": 1000, "posts_periodo": 2}
    assert [tuple(v) for v in view] == [
        ("a", date(2026, 9, 10), date(2026, 9, 1), None),
        ("b", date(2026, 9, 20), date(2026, 9, 1), 42),
    ]
