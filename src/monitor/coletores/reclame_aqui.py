"""Importa os indicadores do Reclame Aqui capturados pelo botão do navegador.

O site bloqueia acesso automatizado (desafio anti-robô do Cloudflare), e o projeto
não contorna essa proteção. Por isso a coleta é semiautomática: o dono abre a
página de cada empresa no próprio navegador e clica no botão
(ferramentas/botao_reclame_aqui.html), que guarda os textos do painel "6 meses".
No fim, o arquivo baixado é importado com `monitor importar-reclame-aqui`.

Este importador segue a interface de Coletor para reaproveitar o executor (uma
transação por perfil, erros em `execucoes`), mas não fica no registro: ele não
roda em `monitor coletar todos` nem no GitHub Actions.
"""

import json
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from monitor.coletores.base import (
    Coletor,
    PerfilAlvo,
    RegistroMetrica,
    RespostaBrutaColetada,
    ResultadoColeta,
)
from monitor.settings import FUSO_REFERENCIA

FONTE_ARQUIVO = "reclame_aqui_botao"
# Janela "6 meses" do site: aceita alguma folga no tamanho do período.
DIAS_JANELA = (150, 200)

# Rótulo exibido no painel -> (código da métrica, tipo do valor)
ROTULOS: dict[str, tuple[str, str]] = {
    "Reclamações recebidas": ("total_reclamacoes", "inteiro"),
    "Reclamações respondidas": ("pct_respondidas", "percentual"),
    "Aguardando resposta": ("aguardando_resposta", "inteiro"),
    "Reclamações resolvidas": ("pct_resolvidas", "percentual"),
    "Voltariam a fazer negócio": ("pct_voltaria_negocio", "percentual"),
    "Reclamações avaliadas": ("reclamacoes_avaliadas", "inteiro"),
    "Nota média do consumidor": ("nota_consumidor", "nota10"),
    "Tempo médio de resposta": ("tempo_resposta_dias", "duracao"),
}

# Nome exibido (sem acento, minúsculo) -> valor gravado em status_reputacao.
REPUTACOES = {
    "ra1000": "RA1000",
    "otima": "Ótimo",
    "otimo": "Ótimo",
    "boa": "Bom",
    "bom": "Bom",
    "regular": "Regular",
    "ruim": "Ruim",
    "nao recomendada": "Não recomendada",
    "sem indice": "Sem índice",
}


class ArquivoInvalido(ValueError):
    pass


class DadosInvalidos(ValueError):
    pass


class CapturaAusente(LookupError):
    pass


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


def inteiro_br(texto: str) -> int:
    """'1.646' -> 1646."""
    limpo = texto.strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*|\d+", limpo):
        raise DadosInvalidos(f"número inteiro inválido: {texto!r}")
    return int(limpo.replace(".", ""))


def decimal_br(texto: str) -> Decimal:
    """'99,9%' -> 99.9; '7,63' -> 7.63; '1.234,5' -> 1234.5."""
    limpo = texto.strip().removesuffix("%").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?|\d+(,\d+)?", limpo):
        raise DadosInvalidos(f"número decimal inválido: {texto!r}")
    return Decimal(limpo.replace(".", "").replace(",", "."))


def duracao_em_dias(texto: str) -> Decimal:
    """'10 dias e 10 horas' -> 10.4167; '23 horas' -> 0.9583; '1 dia' -> 1."""
    normal = _sem_acento(texto)
    partes = {
        unidade: int(m.group(1))
        for unidade, padrao in (("dias", r"(\d+)\s*dias?\b"), ("horas", r"(\d+)\s*horas?\b"),
                                ("min", r"(\d+)\s*min")) if (m := re.search(padrao, normal))
    }
    if not partes:
        raise DadosInvalidos(f"tempo de resposta inválido: {texto!r}")
    dias = (
        Decimal(partes.get("dias", 0))
        + Decimal(partes.get("horas", 0)) / 24
        + Decimal(partes.get("min", 0)) / 1440
    )
    return dias.quantize(Decimal("0.0001"))


def periodo(texto: str | None) -> tuple[date, date]:
    """'Dados de 01/04/2026 até 30/09/2026' -> (2026-04-01, 2026-09-30), só para a aba 6 meses."""
    achado = re.search(r"(\d{2})/(\d{2})/(\d{4})\D+(\d{2})/(\d{2})/(\d{4})", texto or "")
    if not achado:
        raise DadosInvalidos(f"período do painel não encontrado: {texto!r}")
    d1, m1, a1, d2, m2, a2 = (int(g) for g in achado.groups())
    inicio, fim = date(a1, m1, d1), date(a2, m2, d2)
    if not DIAS_JANELA[0] <= (fim - inicio).days <= DIAS_JANELA[1]:
        raise DadosInvalidos(
            f"período de {inicio} a {fim} não é a aba '6 meses': clique no botão com essa aba aberta"
        )
    return inicio, fim


def nota_reclame_aqui(texto: str | None) -> Decimal | None:
    """'... A nota média nos últimos 6 meses 8.5/10.' -> 8.5."""
    if not texto:
        return None
    achado = re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*10", texto)
    if not achado:
        raise DadosInvalidos(f"nota do Reclame Aqui inválida: {texto!r}")
    valor = Decimal(achado.group(1).replace(",", "."))
    if not 0 <= valor <= 10:
        raise DadosInvalidos(f"nota do Reclame Aqui fora da faixa de 0 a 10: {valor}")
    return valor


def reputacao(texto: str | None) -> str | None:
    if not texto:
        return None
    return REPUTACOES.get(_sem_acento(texto), texto.strip().capitalize())


def _valor(rotulo: str, tipo: str, texto: str) -> Decimal | int:
    if tipo == "inteiro":
        return inteiro_br(texto)
    if tipo == "duracao":
        return duracao_em_dias(texto)
    valor = decimal_br(texto)
    limite = 100 if tipo == "percentual" else 10
    if not 0 <= valor <= limite:
        raise DadosInvalidos(f"{rotulo} fora da faixa de 0 a {limite}: {valor}")
    return valor


def metricas_da_captura(captura: dict[str, Any]) -> list[RegistroMetrica]:
    inicio, fim = periodo(captura.get("periodo"))
    capturado_em = datetime.fromisoformat(str(captura["capturado_em"]).replace("Z", "+00:00"))
    referencia = capturado_em.astimezone(FUSO_REFERENCIA).date()
    indicadores = captura.get("indicadores") or {}
    if not indicadores.get("Reclamações recebidas"):
        raise DadosInvalidos("captura sem 'Reclamações recebidas': o painel não foi lido")

    def registro(codigo: str, valor: Any = None, texto: str | None = None) -> RegistroMetrica:
        return RegistroMetrica(
            codigo, valor, texto, periodo_inicio=inicio, periodo_fim=fim, data_referencia=referencia
        )

    registros = [
        # Rótulo ausente no painel vira nulo: desconhecido não é zero.
        registro(codigo, _valor(rotulo, tipo, indicadores[rotulo]) if indicadores.get(rotulo) else None)
        for rotulo, (codigo, tipo) in ROTULOS.items()
    ]
    registros.append(registro("nota_reclame_aqui", nota_reclame_aqui(captura.get("nota"))))
    registros.append(registro("status_reputacao", texto=reputacao(captura.get("reputacao"))))
    return registros


def ler_arquivo(caminho: Path) -> dict[str, dict[str, Any]]:
    """Capturas por slug; se a mesma empresa aparecer mais de uma vez, vale a mais recente."""
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ArquivoInvalido(f"não foi possível ler {caminho}: {erro}") from erro
    if not isinstance(dados, dict) or dados.get("fonte") != FONTE_ARQUIVO:
        raise ArquivoInvalido(f"{caminho} não é um arquivo gerado pelo botão do Reclame Aqui")
    capturas: dict[str, dict[str, Any]] = {}
    for captura in dados.get("capturas") or []:
        slug = str(captura.get("slug") or "").strip().lower()
        if not slug or "capturado_em" not in captura:
            raise ArquivoInvalido(f"captura sem slug ou data: {captura!r}"[:300])
        anterior = capturas.get(slug)
        if anterior is None or str(captura["capturado_em"]) > str(anterior["capturado_em"]):
            capturas[slug] = captura
    return capturas


class ReclameAquiImportador(Coletor):
    nome = "reclame_aqui"
    plataforma = "reclame_aqui"

    def __init__(self, caminho: Path) -> None:
        self._capturas = ler_arquivo(caminho)

    @property
    def slugs(self) -> set[str]:
        return set(self._capturas)

    def coletar(self, perfil: PerfilAlvo) -> ResultadoColeta:
        captura = self._capturas.get(perfil.identificador.strip().lower())
        if captura is None:
            raise CapturaAusente(
                f"empresa não capturada no arquivo: abra "
                f"https://www.reclameaqui.com.br/empresa/{perfil.identificador}/ e clique no botão"
            )
        return ResultadoColeta(
            metricas=metricas_da_captura(captura),
            respostas_brutas=[
                RespostaBrutaColetada(
                    str(captura.get("url") or f"reclame_aqui:{perfil.identificador}"),
                    {k: captura.get(k) for k in ("slug", "capturado_em", "periodo", "reputacao",
                                                 "nota", "indicadores")},
                )
            ],
        )
