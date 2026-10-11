"""O que os coletores das lojas de apps (app_store e google_play) têm em comum."""

import math
import random
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

TIMEOUT_SEGUNDOS = 20.0
PAUSA_ENTRE_APPS_SEGUNDOS = (1.0, 2.0)

Dormir = Callable[[float], None]
Sortear = Callable[[float, float], float]


class AppNaoEncontrado(LookupError):
    pass


class DadosInvalidos(ValueError):
    """A loja respondeu, mas sem nota utilizável. No Google Play, costuma ser o
    sinal de que a biblioteca deixou de entender a página."""


def pausar_entre_apps(dormir: Dormir = time.sleep, sortear: Sortear = random.uniform) -> None:
    dormir(sortear(*PAUSA_ENTRE_APPS_SEGUNDOS))


def nota_validada(nota: Any, total_avaliacoes: Any) -> Decimal:
    """Devolve a nota sem arredondar ou levanta DadosInvalidos. O total só serve
    para validar: sem avaliações não existe nota, e zero não é "desconhecido"."""
    if isinstance(total_avaliacoes, bool) or not isinstance(total_avaliacoes, int):
        raise DadosInvalidos(f"total de avaliações ausente ou inválido: {total_avaliacoes!r}")
    if total_avaliacoes < 0:
        raise DadosInvalidos(f"total de avaliações fora da faixa: {total_avaliacoes}")
    if total_avaliacoes == 0:
        raise DadosInvalidos("app sem avaliações na loja do Brasil; não há nota a gravar")
    if isinstance(nota, bool) or not isinstance(nota, int | float) or not math.isfinite(nota):
        raise DadosInvalidos(f"nota ausente ou inválida: {nota!r}")
    valor = Decimal(str(nota))
    if not 1 <= valor <= 5:
        raise DadosInvalidos(f"nota fora da faixa de 1 a 5: {valor}")
    return valor
