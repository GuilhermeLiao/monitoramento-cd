"""Coletor do Consumidor.gov.br, sem rede: respostas salvas em tests/fixtures."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from monitor.coletores.base import PerfilAlvo
from monitor.coletores.consumidor_gov import (
    URL_BASE,
    ConsumidorGovColetor,
    DadosInvalidos,
    EmpresaNaoEncontrada,
)
from monitor.coletores.executor import executar_coletor
from monitor.coletores.tentativas import ErroTransitorio
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo

FIXTURES = Path(__file__).parent / "fixtures"
PAGINA = (FIXTURES / "consumidor_gov_perfil.html").read_text(encoding="utf-8")
ANUAL = json.loads((FIXTURES / "consumidor_gov_anual.json").read_text(encoding="utf-8"))
ID_BTG = "20191119001741080"
TOKEN = "5_qvD-vUjNsgJO7jmzGupABNDgZu6fQq"
HOJE = date(2026, 10, 24)


def _perfil(identificador: str = ID_BTG, id_: int = 1) -> PerfilAlvo:
    return PerfilAlvo(
        id=id_, instituicao_id=1, plataforma_codigo="consumidor_gov", identificador=identificador
    )


class Relogio:
    def __init__(self):
        self.esperas: list[float] = []

    def dormir(self, segundos: float) -> None:
        self.esperas.append(segundos)

    @staticmethod
    def sortear(minimo: float, maximo: float) -> float:
        return maximo


def _coletor(respostas, relogio=None):
    """`respostas`: uma por requisição; int vira status HTTP, str vira HTML, dict vira JSON."""
    relogio = relogio or Relogio()
    fila = list(respostas)
    chamadas: list[str] = []

    def atender(requisicao: httpx.Request) -> httpx.Response:
        chamadas.append(requisicao.url.path)
        resposta = fila.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        if isinstance(resposta, int):
            return httpx.Response(resposta)
        if isinstance(resposta, str):
            return httpx.Response(200, text=resposta)
        return httpx.Response(200, json=resposta)

    cliente = httpx.Client(base_url=URL_BASE, transport=httpx.MockTransport(atender))
    coletor = ConsumidorGovColetor(
        cliente=cliente, dormir=relogio.dormir, sortear=relogio.sortear, hoje=lambda: HOJE
    )
    return coletor, chamadas, relogio


def _valores(resultado) -> dict:
    return {m.metrica_codigo: m.valor for m in resultado.metricas}


def test_resposta_normal_grava_os_indicadores_do_ano():
    coletor, chamadas, _ = _coletor([PAGINA, ANUAL])
    resultado = coletor.coletar(_perfil())

    assert _valores(resultado) == {
        "total_reclamacoes": 4918,
        "pct_resolvidas": Decimal("78.6"),
        "nota_consumidor": Decimal("1.9"),
        "pct_respondidas": Decimal("98.4"),
        "tempo_resposta_dias": Decimal("9.6"),
    }
    for metrica in resultado.metricas:
        assert (metrica.periodo_inicio, metrica.periodo_fim) == (date(2026, 1, 1), HOJE)
    assert chamadas == [
        f"/pages/empresa/{ID_BTG}/perfil",
        f"/pages/empresa/{TOKEN}/aba/ANUAL/periodo/998/perfil.json",
    ]
    (bruta,) = resultado.respostas_brutas
    assert TOKEN not in bruta.origem
    assert bruta.payload["totalReclamacoes"] == 4918


def test_sem_registros_vira_nulo_nunca_zero():
    sem_registros = {**ANUAL, "totalReclamacoes": 0, "indicadorSolucao": None,
                     "indicadorSatisfacaoAtendimento": None,
                     "indicadorReclamcoesRespondidas": None,
                     "indicadorPrazoMedioRespostas": None}
    coletor, _, _ = _coletor([PAGINA, sem_registros])
    valores = _valores(coletor.coletar(_perfil()))

    assert valores.pop("total_reclamacoes") == 0
    assert set(valores.values()) == {None}


def test_pagina_sem_aba_do_ano():
    coletor, _, _ = _coletor(["<html>Empresa não encontrada</html>"])
    with pytest.raises(EmpresaNaoEncontrada, match="sem a aba do ano"):
        coletor.coletar(_perfil())


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("indicadorSolucao", 101),
        ("indicadorSatisfacaoAtendimento", 0.5),
        ("indicadorReclamcoesRespondidas", "98,4"),
        ("totalReclamacoes", None),
        ("totalReclamacoes", -1),
    ],
)
def test_valor_invalido_nao_e_gravado(campo, valor):
    coletor, _, _ = _coletor([PAGINA, {**ANUAL, campo: valor}])
    with pytest.raises(DadosInvalidos):
        coletor.coletar(_perfil())


def test_campo_ausente():
    resposta = {k: v for k, v in ANUAL.items() if k != "indicadorSolucao"}
    coletor, _, _ = _coletor([PAGINA, resposta])
    with pytest.raises(DadosInvalidos, match="ausente"):
        coletor.coletar(_perfil())


def test_resposta_nao_json():
    coletor, _, _ = _coletor([PAGINA, "<html>erro</html>"])
    with pytest.raises(DadosInvalidos, match="JSON"):
        coletor.coletar(_perfil())


def test_falha_no_json_repete_abrindo_a_pagina_de_novo():
    # O token é da sessão: uma nova tentativa precisa de página (e token) novos.
    coletor, chamadas, relogio = _coletor([PAGINA, 500, PAGINA, ANUAL])
    resultado = coletor.coletar(_perfil())

    assert _valores(resultado)["total_reclamacoes"] == 4918
    assert [c.endswith("/perfil") for c in chamadas] == [True, False, True, False]
    assert relogio.esperas == [2.0]


def test_desiste_na_terceira_falha():
    coletor, chamadas, _ = _coletor([503, 503, 503])
    with pytest.raises(ErroTransitorio, match="HTTP 503"):
        coletor.coletar(_perfil())
    assert len(chamadas) == 3


def test_identificador_invalido_nao_chama_o_site():
    coletor, chamadas, _ = _coletor([])
    with pytest.raises(ValueError, match="número da URL do perfil"):
        coletor.coletar(_perfil("Banco BTG Pactual"))
    assert chamadas == []


def test_pausa_entre_empresas():
    coletor, _, relogio = _coletor([PAGINA, ANUAL, PAGINA, ANUAL])
    coletor.coletar(_perfil(ID_BTG, 1))
    assert relogio.esperas == []
    coletor.coletar(_perfil("20150204000053619", 2))
    assert relogio.esperas == [2.0]


# ----------------------------------------------------------------------- banco


def test_coleta_idempotente_e_aparece_na_view(fabrica):
    config = [
        {
            "nome": "Banco Exemplo",
            "nome_curto": "exemplo",
            "perfis": {"consumidor_gov": [{"identificador": ID_BTG}]},
        }
    ]
    with fabrica.begin() as sessao:
        repo.sincronizar_config(sessao, validar_config(config))

    for _ in range(2):
        coletor, _, _ = _coletor([PAGINA, ANUAL])
        resultado = executar_coletor(coletor, fabrica)
        assert (resultado.status, resultado.perfis_ok) == ("sucesso", 1)

    with fabrica() as sessao:
        linhas = sessao.execute(
            text(
                "SELECT metrica_codigo, valor, periodo_inicio, periodo_fim "
                "FROM vw_metricas_atuais WHERE plataforma_codigo = 'consumidor_gov'"
            )
        ).all()
    valores = {codigo: (valor, inicio, fim) for codigo, valor, inicio, fim in linhas}
    assert len(linhas) == 5
    assert valores["total_reclamacoes"] == (Decimal("4918"), date(2026, 1, 1), HOJE)
    assert valores["nota_consumidor"][0] == Decimal("1.9")


# ------------------------------------------------------------------------ live


@pytest.mark.live
def test_live_consumidor_gov():
    valores = _valores(ConsumidorGovColetor().coletar(_perfil()))
    assert valores["total_reclamacoes"] > 0
    assert 1 <= valores["nota_consumidor"] <= 5
