"""Importador do Reclame Aqui (arquivo gerado pelo botão do navegador)."""

import copy
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from monitor.coletores.base import PerfilAlvo
from monitor.coletores.executor import executar_coletor
from monitor.coletores.reclame_aqui import (
    ArquivoInvalido,
    CapturaAusente,
    DadosInvalidos,
    ReclameAquiImportador,
    decimal_br,
    duracao_em_dias,
    inteiro_br,
    periodo,
    reputacao,
)
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo

FIXTURE = Path(__file__).parent / "fixtures" / "reclame_aqui_captura.json"
ARQUIVO = json.loads(FIXTURE.read_text(encoding="utf-8"))
SLUG = "empresa-exemplo"


def _arquivo(tmp_path, dados=None) -> Path:
    caminho = tmp_path / "captura.json"
    caminho.write_text(json.dumps(dados or ARQUIVO, ensure_ascii=False), encoding="utf-8")
    return caminho


def _perfil(slug: str = SLUG) -> PerfilAlvo:
    return PerfilAlvo(id=1, instituicao_id=1, plataforma_codigo="reclame_aqui", identificador=slug)


def test_captura_da_tela_vira_metricas_da_janela_de_6_meses():
    resultado = ReclameAquiImportador(FIXTURE).coletar(_perfil())
    valores = {m.metrica_codigo: (m.valor, m.valor_texto) for m in resultado.metricas}

    assert valores == {
        "total_reclamacoes": (1646, None),
        "pct_respondidas": (Decimal("99.9"), None),
        "aguardando_resposta": (2, None),
        "pct_resolvidas": (Decimal("89.3"), None),
        "pct_voltaria_negocio": (Decimal("75.9"), None),
        "reclamacoes_avaliadas": (910, None),
        "nota_consumidor": (Decimal("7.63"), None),
        "tempo_resposta_dias": (Decimal("10.4167"), None),
        "nota_reclame_aqui": (Decimal("8.5"), None),
        "status_reputacao": (None, "Ótimo"),
    }
    for m in resultado.metricas:
        assert (m.periodo_inicio, m.periodo_fim) == (date(2026, 4, 1), date(2026, 9, 30))
        assert m.data_referencia == date(2026, 10, 24)


def test_slug_sem_diferenciar_maiusculas():
    assert ReclameAquiImportador(FIXTURE).coletar(_perfil("Empresa-Exemplo")).metricas


def test_empresa_nao_capturada():
    with pytest.raises(CapturaAusente, match="reclameaqui.com.br/empresa/outra/"):
        ReclameAquiImportador(FIXTURE).coletar(_perfil("outra"))


def test_rotulo_ausente_vira_nulo_nunca_zero(tmp_path):
    dados = copy.deepcopy(ARQUIVO)
    del dados["capturas"][0]["indicadores"]["Voltariam a fazer negócio"]
    dados["capturas"][0]["nota"] = None
    resultado = ReclameAquiImportador(_arquivo(tmp_path, dados)).coletar(_perfil())
    valores = {m.metrica_codigo: m.valor for m in resultado.metricas}
    assert valores["pct_voltaria_negocio"] is None
    assert valores["nota_reclame_aqui"] is None


def test_aba_diferente_de_6_meses_e_recusada(tmp_path):
    dados = copy.deepcopy(ARQUIVO)
    dados["capturas"][0]["periodo"] = "Dados de 01/10/2025 até 30/09/2026"
    with pytest.raises(DadosInvalidos, match="6 meses"):
        ReclameAquiImportador(_arquivo(tmp_path, dados)).coletar(_perfil())


def test_sem_total_de_reclamacoes_e_erro(tmp_path):
    dados = copy.deepcopy(ARQUIVO)
    del dados["capturas"][0]["indicadores"]["Reclamações recebidas"]
    with pytest.raises(DadosInvalidos, match="Reclamações recebidas"):
        ReclameAquiImportador(_arquivo(tmp_path, dados)).coletar(_perfil())


def test_percentual_fora_da_faixa(tmp_path):
    dados = copy.deepcopy(ARQUIVO)
    dados["capturas"][0]["indicadores"]["Reclamações resolvidas"] = "189,3%"
    with pytest.raises(DadosInvalidos, match="fora da faixa"):
        ReclameAquiImportador(_arquivo(tmp_path, dados)).coletar(_perfil())


def test_mesma_empresa_duas_vezes_vale_a_mais_recente(tmp_path):
    dados = copy.deepcopy(ARQUIVO)
    nova = copy.deepcopy(dados["capturas"][0])
    nova["capturado_em"] = "2026-10-25T10:00:00.000Z"
    nova["indicadores"]["Reclamações recebidas"] = "1.700"
    dados["capturas"].insert(0, nova)
    resultado = ReclameAquiImportador(_arquivo(tmp_path, dados)).coletar(_perfil())
    assert resultado.metricas[0].valor == 1700


@pytest.mark.parametrize(
    "conteudo", ["isto não é json", json.dumps({"capturas": []}), json.dumps([1, 2])]
)
def test_arquivo_invalido(tmp_path, conteudo):
    caminho = tmp_path / "x.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ArquivoInvalido):
        ReclameAquiImportador(caminho)


# ---------------------------------------------------------------- conversões


@pytest.mark.parametrize(("texto", "esperado"), [("1.646", 1646), ("2", 2), ("12.345.678", 12345678)])
def test_inteiro_br(texto, esperado):
    assert inteiro_br(texto) == esperado


@pytest.mark.parametrize("texto", ["1,5", "", "mil", "1.64"])
def test_inteiro_br_invalido(texto):
    with pytest.raises(DadosInvalidos):
        inteiro_br(texto)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("99,9%", "99.9"), ("100%", "100"), ("7,63", "7.63"), ("1.234,5", "1234.5")],
)
def test_decimal_br(texto, esperado):
    assert decimal_br(texto) == Decimal(esperado)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("10 dias e 10 horas", "10.4167"),
        ("1 dia e 1 hora", "1.0417"),
        ("23 horas", "0.9583"),
        ("5 dias", "5.0000"),
        ("2 horas e 30 minutos", "0.1042"),
    ],
)
def test_duracao_em_dias(texto, esperado):
    assert duracao_em_dias(texto) == Decimal(esperado)


def test_duracao_invalida():
    with pytest.raises(DadosInvalidos):
        duracao_em_dias("sem resposta")


def test_periodo():
    assert periodo("Dados de 01/04/2026 até 30/09/2026") == (date(2026, 4, 1), date(2026, 9, 30))


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [("ÓTIMA", "Ótimo"), ("RA1000", "RA1000"), ("NÃO RECOMENDADA", "Não recomendada"),
     ("Sem índice", "Sem índice"), ("NOVA", "Nova"), (None, None)],
)
def test_reputacao(texto, esperado):
    assert reputacao(texto) == esperado


# ----------------------------------------------------------------------- banco


def test_importacao_idempotente_e_aparece_na_view(fabrica):
    config = [
        {
            "nome": "Banco Exemplo",
            "nome_curto": "exemplo",
            "perfis": {"reclame_aqui": [{"identificador": SLUG}, {"identificador": "faltou"}]},
        }
    ]
    with fabrica.begin() as sessao:
        repo.sincronizar_config(sessao, validar_config(config))

    for _ in range(2):
        resultado = executar_coletor(ReclameAquiImportador(FIXTURE), fabrica)
    assert (resultado.status, resultado.perfis_ok, resultado.perfis_erro) == ("parcial", 1, 1)
    assert resultado.erros[0]["tipo"] == "CapturaAusente"

    with fabrica() as sessao:
        linhas = dict(
            sessao.execute(
                text(
                    "SELECT metrica_codigo, coalesce(valor::text, valor_texto) FROM vw_metricas_atuais "
                    "WHERE plataforma_codigo = 'reclame_aqui'"
                )
            ).all()
        )
    assert len(linhas) == 10
    assert linhas["total_reclamacoes"] == "1646"
    assert linhas["status_reputacao"] == "Ótimo"
