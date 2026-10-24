"""Registro dos coletores disponíveis para a CLI.

Para adicionar um coletor: crie o módulo com a classe decorada com @registrar
e importe-o no final deste arquivo.
"""

from monitor.coletores.base import Coletor

COLETORES: dict[str, type[Coletor]] = {}
# Atalhos da CLI para rodar vários coletores de uma vez (`monitor coletar lojas`).
GRUPOS: dict[str, tuple[str, ...]] = {"lojas": ("app_store", "google_play")}


def registrar(classe: type[Coletor]) -> type[Coletor]:
    if classe.nome in COLETORES:
        raise ValueError(f"Coletor duplicado: {classe.nome}")
    COLETORES[classe.nome] = classe
    return classe


# Imports dos coletores (um por linha).
from monitor.coletores import app_store  # noqa: E402,F401
from monitor.coletores import google_play  # noqa: E402,F401
from monitor.coletores import consumidor_gov  # noqa: E402,F401
from monitor.coletores import instagram  # noqa: E402,F401
