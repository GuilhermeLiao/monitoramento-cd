from pathlib import Path

import pytest
from pydantic import ValidationError

from monitor.config_loader import ConfigInvalida, carregar_config, validar_config

EXEMPLO = {
    "nome": "Banco Exemplo",
    "nome_curto": "exemplo",
    "cnpj": "00.000.000/0001-00",
    "perfis": {
        "app_store": [{"identificador": 123456789, "rotulo": "App PF"}],
        "instagram": [{"identificador": "bancoexemplo"}],
    },
}


def test_config_valida():
    (inst,) = validar_config([EXEMPLO])
    assert inst.cnpj == "00.000.000/0001-00"
    # ID numérico sem aspas no YAML vira texto.
    assert inst.perfis["app_store"][0].identificador == "123456789"
    assert inst.perfis["instagram"][0].rotulo is None


def test_cnpj_sem_pontuacao_e_normalizado():
    (inst,) = validar_config([{**EXEMPLO, "cnpj": "00000000000100"}])
    assert inst.cnpj == "00.000.000/0001-00"


def test_arquivo_vazio_e_config_vazia():
    assert validar_config(None) == []


@pytest.mark.parametrize(
    "alteracao",
    [
        {"cnpj": "123"},
        {"nome_curto": "Com Espaço"},
        {"nome": ""},
        {"campo_desconhecido": 1},
        {"perfis": {"instagram": [{"rotulo": "sem identificador"}]}},
        {"perfis": {"instagram": [{"identificador": ""}]}},
    ],
)
def test_campos_invalidos(alteracao):
    with pytest.raises(ValidationError):
        validar_config([{**EXEMPLO, **alteracao}])


def test_nome_curto_repetido():
    with pytest.raises(ConfigInvalida, match="nome_curto repetido"):
        validar_config([EXEMPLO, {**EXEMPLO, "cnpj": None, "perfis": {}}])


def test_perfil_repetido_entre_instituicoes():
    outra = {"nome": "Outra", "nome_curto": "outra", "perfis": EXEMPLO["perfis"]}
    with pytest.raises(ConfigInvalida, match="perfil repetido"):
        validar_config([EXEMPLO, outra])


def test_yaml_de_exemplo_do_repositorio_carrega():
    raiz = Path(__file__).resolve().parents[1]
    assert isinstance(carregar_config(raiz / "config" / "instituicoes.yaml"), list)
