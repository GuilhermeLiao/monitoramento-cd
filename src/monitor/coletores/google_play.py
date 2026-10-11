"""Nota média dos apps no Google Play do Brasil."""

import random
import time

from monitor.coletores import registrar
from monitor.coletores.adaptador_google_play import FonteGooglePlay, GooglePlayScraper
from monitor.coletores.base import (
    Coletor,
    PerfilAlvo,
    RegistroMetrica,
    RespostaBrutaColetada,
    ResultadoColeta,
)
from monitor.coletores.lojas import Dormir, Sortear, nota_validada, pausar_entre_apps
from monitor.coletores.tentativas import com_retentativas


@registrar
class GooglePlayColetor(Coletor):
    nome = "google_play"
    plataforma = "google_play"

    def __init__(
        self,
        fonte: FonteGooglePlay | None = None,
        dormir: Dormir = time.sleep,
        sortear: Sortear = random.uniform,
    ) -> None:
        self._fonte = fonte or GooglePlayScraper()
        self._dormir = dormir
        self._sortear = sortear
        self._primeiro = True

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        if not self._primeiro:
            pausar_entre_apps(self._dormir, self._sortear)
        self._primeiro = False

        app = com_retentativas(
            lambda: self._fonte.buscar_app(perfil.identificador),
            dormir=self._dormir,
            sortear=self._sortear,
        )
        nota = nota_validada(app.nota, app.total_avaliacoes)
        return ResultadoColeta(
            metricas=[RegistroMetrica("nota_media", nota)],
            respostas_brutas=[RespostaBrutaColetada(app.origem, app.bruto)],
        )
