"""Dashboard local: leitura do banco e geração da página."""

import json
import re

import httpx
import pytest
from sqlalchemy import text

from monitor.coletores.app_store import AppStoreColetor
from monitor.coletores.executor import executar_coletor
from monitor.config_loader import validar_config
from monitor.db import repositorios as repo
from monitor.painel import carregar_dados, gerar_html


def _dados_da_pagina(html: str) -> dict:
    achado = re.search(r"const DADOS = (.*?);\n", html)
    assert achado, "dados não embutidos na página"
    return json.loads(achado.group(1).replace("<\\/", "</"))


def test_texto_do_banco_nao_fecha_a_tag_script():
    dados = {"instituicoes": [[1, "Banco </script><script>alert(1)</script>", "x"]],
             "perfis": [], "metricas": [], "atuais": [], "historico": [], "posts": [],
             "execucoes": [], "gerado_em": "hoje"}
    html = gerar_html(dados, "teste")
    assert "</script><script>alert(1)" not in html
    assert _dados_da_pagina(html)["instituicoes"][0][1].startswith("Banco </script>")


def test_carrega_do_banco_sem_escrever(fabrica, engine):
    config = [{"nome": "Banco Exemplo", "nome_curto": "exemplo",
               "perfis": {"app_store": [{"identificador": "814456780"}]}}]
    with fabrica.begin() as sessao:
        repo.sincronizar_config(sessao, validar_config(config))
    resposta = {"resultCount": 1, "results": [{"trackId": 814456780, "averageUserRating": 4.5,
                                                "userRatingCount": 10}]}
    cliente = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=resposta)))
    executar_coletor(AppStoreColetor(cliente=cliente, dormir=lambda s: None), fabrica)

    dados = carregar_dados(engine)

    assert [i[1] for i in dados["instituicoes"]] == ["Banco Exemplo"]
    assert [(a[1], a[2]) for a in dados["atuais"]] == [("nota_media", 4.5)]
    assert dados["execucoes"][0][:2] == ["app_store", "sucesso"]
    assert _dados_da_pagina(gerar_html(dados, "teste"))["origem"] == "teste"
    # A transação de leitura não deixa a conexão do pool em modo só leitura.
    with engine.begin() as conexao:
        assert conexao.execute(text("SHOW transaction_read_only")).scalar() == "off"


@pytest.mark.parametrize("campo", ["perfis", "atuais", "historico", "posts"])
def test_pagina_aceita_listas_vazias(campo):
    dados = {"instituicoes": [], "perfis": [], "metricas": [], "atuais": [], "historico": [],
             "posts": [], "execucoes": [], "gerado_em": "hoje"}
    assert _dados_da_pagina(gerar_html(dados, "x"))[campo] == []
