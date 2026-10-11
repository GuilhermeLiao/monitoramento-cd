"""Coletor de loja de ponta a ponta no Postgres (branch dev do Neon), sem rede."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import func, select, text

from monitor.coletores.app_store import AppStoreColetor
from monitor.coletores.executor import executar_coletor
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo
from monitor.db.models import SnapshotMetrica

RESPOSTA = json.loads(
    (Path(__file__).parent / "fixtures" / "app_store_lookup.json").read_text(encoding="utf-8")
)
CONFIG = [
    {
        "nome": "Banco Exemplo",
        "nome_curto": "exemplo",
        "perfis": {
            "app_store": [
                {"identificador": "814456780", "rotulo": "App PF"},
                {"identificador": "1", "rotulo": "App removido"},
            ]
        },
    }
]


def _coletor() -> AppStoreColetor:
    cliente = httpx.Client(
        transport=httpx.MockTransport(lambda requisicao: httpx.Response(200, json=RESPOSTA))
    )
    return AppStoreColetor(cliente=cliente, dormir=lambda segundos: None)


def test_coleta_idempotente_isola_perfil_invalido_e_aparece_na_view(fabrica):
    with fabrica.begin() as sessao:
        repo.sincronizar_config(sessao, validar_config(CONFIG))

    executar_coletor(_coletor(), fabrica)
    resultado = executar_coletor(_coletor(), fabrica)

    assert (resultado.status, resultado.perfis_ok, resultado.perfis_erro) == ("parcial", 1, 1)
    (erro,) = resultado.erros
    assert (erro["identificador"], erro["tipo"]) == ("1", "AppNaoEncontrado")
    with fabrica() as sessao:
        assert sessao.scalar(select(func.count()).select_from(SnapshotMetrica)) == 1
        linha = sessao.execute(
            text(
                "SELECT instituicao, perfil_rotulo, plataforma_codigo, metrica_codigo, valor "
                "FROM vw_metricas_atuais"
            )
        ).one()
    assert tuple(linha) == ("Banco Exemplo", "App PF", "app_store", "nota_media", Decimal("4.82291"))
