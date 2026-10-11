"""Retentativa com backoff exponencial e jitter, comum aos coletores."""

import logging
import random
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

TENTATIVAS = 3
ESPERA_BASE_SEGUNDOS = 1.0


class ErroTransitorio(Exception):
    """Falha que vale tentar de novo: timeout, erro de conexão, HTTP 429 ou 5xx."""


def com_retentativas[T](
    operacao: Callable[[], T],
    *,
    tentativas: int = TENTATIVAS,
    dormir: Callable[[float], None] = time.sleep,
    sortear: Callable[[float, float], float] = random.uniform,
) -> T:
    """Repete `operacao` enquanto ela levantar ErroTransitorio. Outras exceções sobem na hora."""
    for tentativa in range(1, tentativas + 1):
        try:
            return operacao()
        except ErroTransitorio as erro:
            if tentativa == tentativas:
                raise
            espera = ESPERA_BASE_SEGUNDOS * 2 ** (tentativa - 1)
            espera += sortear(0, espera)
            log.warning(
                "falha transitoria, nova tentativa",
                extra={"tentativa": tentativa, "espera_segundos": round(espera, 2), "erro": str(erro)},
            )
            dormir(espera)
    raise AssertionError("inalcançável")
