"""Registro dos coletores disponíveis para a CLI.

Para adicionar um coletor: crie o módulo com a classe decorada com @registrar
e importe-o no final deste arquivo.
"""

from monitor.coletores.base import Coletor

COLETORES: dict[str, type[Coletor]] = {}


def registrar(classe: type[Coletor]) -> type[Coletor]:
    if classe.nome in COLETORES:
        raise ValueError(f"Coletor duplicado: {classe.nome}")
    COLETORES[classe.nome] = classe
    return classe


# Imports dos coletores (um por linha), por exemplo:
# from monitor.coletores import app_store  # noqa: E402,F401
