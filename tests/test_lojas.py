"""Coletores das lojas de apps, sem rede: respostas salvas em tests/fixtures."""

import copy
import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from google_play_scraper.exceptions import ExtraHTTPError, NotFoundError

from monitor.coletores import adaptador_google_play
from monitor.coletores.adaptador_google_play import GooglePlayScraper
from monitor.coletores.app_store import AppStoreColetor
from monitor.coletores.base import PerfilAlvo
from monitor.coletores.google_play import GooglePlayColetor
from monitor.coletores.lojas import AppNaoEncontrado, DadosInvalidos, nota_validada
from monitor.coletores.tentativas import ErroTransitorio

FIXTURES = Path(__file__).parent / "fixtures"
ID_APP_STORE = "814456780"
PACOTE = "com.nu.production"


def _fixture(nome: str) -> dict:
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


def _perfil(plataforma: str, identificador: str, id_: int = 1) -> PerfilAlvo:
    return PerfilAlvo(
        id=id_, instituicao_id=1, plataforma_codigo=plataforma, identificador=identificador
    )


class Relogio:
    """Substitui sleep e random: registra as esperas sem dormir."""

    def __init__(self):
        self.esperas: list[float] = []

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)

    @staticmethod
    def sortear(minimo: float, maximo: float) -> float:
        return maximo


# ------------------------------------------------------------------- App Store


def _app_store(respostas, relogio=None):
    """`respostas`: uma por chamada; int vira status HTTP sem corpo, exceção é levantada."""
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
        return httpx.Response(200, json=resposta)

    coletor = AppStoreColetor(
        cliente=httpx.Client(transport=httpx.MockTransport(atender)),
        dormir=relogio.dormir,
        sortear=relogio.sortear,
    )
    return coletor, chamadas, relogio


def test_app_store_resposta_normal():
    coletor, chamadas, _ = _app_store([_fixture("app_store_lookup.json")])
    resultado = coletor.coletar(_perfil("app_store", ID_APP_STORE))

    (metrica,) = resultado.metricas
    assert (metrica.metrica_codigo, metrica.valor) == ("nota_media", Decimal("4.82291"))
    assert dict(chamadas[0].url.params) == {"id": ID_APP_STORE, "country": "br"}
    (bruta,) = resultado.respostas_brutas
    assert bruta.payload["averageUserRating"] == 4.82291
    assert "description" not in bruta.payload
    assert "screenshotUrls" not in bruta.payload


def test_app_store_results_vazio():
    coletor, _, _ = _app_store([{"resultCount": 0, "results": []}])
    with pytest.raises(AppNaoEncontrado, match="removido ou não existir na loja do Brasil"):
        coletor.coletar(_perfil("app_store", "1"))


def test_app_store_lote_faz_uma_chamada_e_isola_o_id_que_faltou():
    coletor, chamadas, _ = _app_store([_fixture("app_store_lookup.json")])
    existente = _perfil("app_store", ID_APP_STORE, 1)
    removido = _perfil("app_store", "1", 2)
    invalido = _perfil("app_store", "com.exemplo", 3)

    coletor.preparar([existente, removido, invalido])
    assert coletor.coletar(existente).metricas[0].valor == Decimal("4.82291")
    with pytest.raises(AppNaoEncontrado):
        coletor.coletar(removido)
    with pytest.raises(ValueError, match="ID numérico"):
        coletor.coletar(invalido)

    assert len(chamadas) == 1
    assert chamadas[0].url.params["id"] == f"{ID_APP_STORE},1"


@pytest.mark.parametrize("campo", ["averageUserRating", "userRatingCount"])
def test_app_store_nota_ou_total_ausente(campo):
    resposta = _fixture("app_store_lookup.json")
    del resposta["results"][0][campo]
    coletor, _, _ = _app_store([resposta])
    with pytest.raises(DadosInvalidos, match="ausente"):
        coletor.coletar(_perfil("app_store", ID_APP_STORE))


def test_app_store_erro_http_com_retentativa():
    coletor, chamadas, relogio = _app_store(
        [503, httpx.ConnectTimeout("tempo esgotado"), _fixture("app_store_lookup.json")]
    )
    resultado = coletor.coletar(_perfil("app_store", ID_APP_STORE))

    assert resultado.metricas[0].valor == Decimal("4.82291")
    assert len(chamadas) == 3
    # Backoff exponencial (1 s e 2 s) mais o jitter, que aqui é sempre o máximo.
    assert relogio.esperas == [2.0, 4.0]


def test_app_store_desiste_na_terceira_falha_e_marca_o_lote_inteiro():
    coletor, chamadas, _ = _app_store([503, 503, 503])
    perfis = [_perfil("app_store", ID_APP_STORE, 1), _perfil("app_store", "2", 2)]
    coletor.preparar(perfis)
    for perfil in perfis:
        with pytest.raises(ErroTransitorio, match="HTTP 503"):
            coletor.coletar(perfil)
    assert len(chamadas) == 3


def test_app_store_erro_http_definitivo_nao_e_repetido():
    coletor, chamadas, _ = _app_store([400])
    with pytest.raises(httpx.HTTPStatusError):
        coletor.coletar(_perfil("app_store", ID_APP_STORE))
    assert len(chamadas) == 1


# ----------------------------------------------------------------- Google Play


def _google_play(monkeypatch, respostas, relogio=None):
    """`respostas`: uma por chamada à biblioteca; exceção é levantada."""
    relogio = relogio or Relogio()
    fila = list(respostas)
    chamadas: list[tuple] = []

    def app_falso(pacote, lang, country):
        chamadas.append((pacote, lang, country))
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    monkeypatch.setattr(adaptador_google_play.google_play_scraper, "app", app_falso)
    coletor = GooglePlayColetor(
        fonte=GooglePlayScraper(), dormir=relogio.dormir, sortear=relogio.sortear
    )
    return coletor, chamadas, relogio


def test_google_play_resposta_normal(monkeypatch):
    resposta = _fixture("google_play_app.json")
    # Texto livre de consumidor nunca pode chegar a respostas_brutas.
    resposta["comments"] = ["Fulano: não consigo acessar minha conta"]
    coletor, chamadas, _ = _google_play(monkeypatch, [resposta])
    resultado = coletor.coletar(_perfil("google_play", PACOTE))

    (metrica,) = resultado.metricas
    assert (metrica.metrica_codigo, metrica.valor) == ("nota_media", Decimal("4.75186"))
    assert chamadas == [(PACOTE, "pt", "br")]
    (bruta,) = resultado.respostas_brutas
    assert bruta.origem.startswith("google-play-scraper==")
    assert bruta.payload["score"] == 4.75186
    assert "comments" not in bruta.payload
    assert "description" not in bruta.payload


def test_google_play_pacote_inexistente(monkeypatch):
    coletor, chamadas, _ = _google_play(monkeypatch, [NotFoundError("App not found(404).")])
    with pytest.raises(AppNaoEncontrado, match="com.nao.existe"):
        coletor.coletar(_perfil("google_play", "com.nao.existe"))
    assert len(chamadas) == 1


@pytest.mark.parametrize("campo", ["score", "ratings"])
def test_google_play_nota_ou_total_ausente(monkeypatch, campo):
    # É como a biblioteca responde quando deixa de entender a página da loja.
    resposta = _fixture("google_play_app.json")
    resposta[campo] = None
    coletor, _, _ = _google_play(monkeypatch, [resposta])
    with pytest.raises(DadosInvalidos, match="ausente"):
        coletor.coletar(_perfil("google_play", PACOTE))


def test_google_play_erro_http_com_retentativa(monkeypatch):
    coletor, chamadas, relogio = _google_play(
        monkeypatch,
        [
            ExtraHTTPError("App not found. Status code 503 returned."),
            TimeoutError("timed out"),
            _fixture("google_play_app.json"),
        ],
    )
    resultado = coletor.coletar(_perfil("google_play", PACOTE))

    assert resultado.metricas[0].valor == Decimal("4.75186")
    assert len(chamadas) == 3
    assert relogio.esperas == [2.0, 4.0]


def test_google_play_desiste_na_terceira_falha(monkeypatch):
    erro = ExtraHTTPError("App not found. Status code 429 returned.")
    coletor, chamadas, _ = _google_play(monkeypatch, [erro, erro, erro])
    with pytest.raises(ErroTransitorio, match="HTTP 429"):
        coletor.coletar(_perfil("google_play", PACOTE))
    assert len(chamadas) == 3


def test_google_play_pausa_entre_apps(monkeypatch):
    resposta = _fixture("google_play_app.json")
    coletor, _, relogio = _google_play(monkeypatch, [resposta, copy.deepcopy(resposta)])
    coletor.coletar(_perfil("google_play", PACOTE, 1))
    assert relogio.esperas == []
    coletor.coletar(_perfil("google_play", "com.outro.app", 2))
    assert relogio.esperas == [2.0]


# ------------------------------------------------------------------- validação


@pytest.mark.parametrize(
    ("nota", "total"),
    [
        (None, 10),
        ("4.5", 10),
        (float("nan"), 10),
        (0, 10),
        (5.1, 10),
        (4.5, None),
        (4.5, -1),
        (4.5, 0),
        (0, 0),
        (True, 10),
    ],
)
def test_nota_invalida_nunca_vira_valor(nota, total):
    with pytest.raises(DadosInvalidos):
        nota_validada(nota, total)


def test_nota_valida_nao_e_arredondada():
    assert nota_validada(4.82291, 1652172) == Decimal("4.82291")
    assert nota_validada(5, 1) == Decimal("5")


# ------------------------------------------------------------------------ live


@pytest.mark.live
def test_live_app_store():
    resultado = AppStoreColetor().coletar(_perfil("app_store", ID_APP_STORE))
    assert 1 <= resultado.metricas[0].valor <= 5


@pytest.mark.live
def test_live_google_play():
    resultado = GooglePlayColetor().coletar(_perfil("google_play", PACOTE))
    assert 1 <= resultado.metricas[0].valor <= 5
