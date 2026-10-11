"""Único ponto de contato com a biblioteca google-play-scraper.

O coletor só conhece `FonteGooglePlay`. Para trocar a biblioteca (por um serviço
pago, por exemplo), escreva outra classe com `buscar_app` e passe-a ao coletor.
"""

import re
import socket
import ssl
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Protocol

from monitor.coletores.lojas import TIMEOUT_SEGUNDOS, AppNaoEncontrado
from monitor.coletores.tentativas import ErroTransitorio

# A biblioteca desliga a verificação de certificados HTTPS de todo o processo ao
# ser importada; restauramos o padrão logo em seguida.
_contexto_https = ssl._create_default_https_context
import google_play_scraper  # noqa: E402
from google_play_scraper.exceptions import ExtraHTTPError, NotFoundError  # noqa: E402

ssl._create_default_https_context = _contexto_https

IDIOMA = "pt"
PAIS = "br"
# Só o necessário para conferir a nota depois. `comments` traz texto livre de
# consumidores e nunca pode ser gravado; descrição e imagens ficam de fora (espaço).
CAMPOS_BRUTOS = (
    "appId",
    "title",
    "score",
    "ratings",
    "reviews",
    "histogram",
    "installs",
    "version",
    "updated",
)


@dataclass(frozen=True)
class AppGooglePlay:
    """Valores como vieram da fonte, sem validar: quem valida é o coletor."""

    nota: Any
    total_avaliacoes: Any
    origem: str
    bruto: dict[str, Any]


class FonteGooglePlay(Protocol):
    def buscar_app(self, pacote: str) -> AppGooglePlay:
        """Levanta AppNaoEncontrado se o pacote não existir e ErroTransitorio em
        falhas que valem nova tentativa."""
        ...


class GooglePlayScraper:
    origem = f"google-play-scraper=={version('google-play-scraper')} app()"

    def buscar_app(self, pacote: str) -> AppGooglePlay:
        # A biblioteca não aceita timeout; o padrão do socket vale só durante a chamada.
        timeout_anterior = socket.getdefaulttimeout()
        socket.setdefaulttimeout(TIMEOUT_SEGUNDOS)
        try:
            dados = google_play_scraper.app(pacote, lang=IDIOMA, country=PAIS)
        except NotFoundError as erro:
            raise AppNaoEncontrado(
                f"pacote {pacote} não encontrado no Google Play do Brasil"
            ) from erro
        except ExtraHTTPError as erro:
            status = re.search(r"Status code (\d+)", str(erro))
            if status and (int(status[1]) == 429 or int(status[1]) >= 500):
                raise ErroTransitorio(f"Google Play respondeu HTTP {status[1]}") from erro
            raise
        except OSError as erro:  # URLError, timeout e queda de conexão
            raise ErroTransitorio(f"falha de rede no Google Play: {erro!r}") from erro
        finally:
            socket.setdefaulttimeout(timeout_anterior)
        return AppGooglePlay(
            nota=dados.get("score"),
            total_avaliacoes=dados.get("ratings"),
            origem=self.origem,
            bruto={campo: dados[campo] for campo in CAMPOS_BRUTOS if campo in dados},
        )
