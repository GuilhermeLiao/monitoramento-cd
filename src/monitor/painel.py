"""Dashboard local: lê o banco (só leitura) e gera uma página HTML autocontida."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from monitor.db.session import criar_engine
from monitor.settings import FUSO_REFERENCIA, Settings, get_settings

MODELO = Path(__file__).parent / "ferramentas" / "painel.html"


def engine_do_painel(settings: Settings | None = None) -> tuple[Engine, str]:
    """Engine do banco do painel e uma descrição curta da origem (host, sem senha)."""
    settings = settings or get_settings()
    url = settings.painel_database_url or settings.database_url
    origem = "PAINEL_DATABASE_URL" if settings.painel_database_url else "DATABASE_URL (.env)"
    engine = criar_engine(settings.model_copy(update={"database_url": url, "db_schema": None}))
    host = make_url(engine.url).host or "?"
    return engine, f"{host.split('.')[0]} via {origem}"


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, datetime):
        return valor.astimezone(FUSO_REFERENCIA).isoformat(timespec="minutes")
    if isinstance(valor, date):
        return valor.isoformat()
    return valor


def _linhas(conexao: Connection, sql: str, **params: Any) -> list[list[Any]]:
    return [[_json(v) for v in linha] for linha in conexao.execute(text(sql), params)]


def carregar_dados(engine: Engine) -> dict[str, Any]:
    with engine.connect() as conexao:
        # Garantia extra: o painel nunca escreve, mesmo se o usuário puder. Vale só para
        # esta transação, para não contaminar conexões reaproveitadas do pool.
        conexao.execute(text("SET TRANSACTION READ ONLY"))
        instituicoes = _linhas(
            conexao,
            "SELECT id, nome, nome_curto, segmento FROM instituicoes WHERE ativo ORDER BY nome",
        )
        perfis = _linhas(
            conexao,
            """SELECT p.id, p.instituicao_id, p.plataforma_codigo, p.identificador, p.rotulo
               FROM perfis p JOIN instituicoes i ON i.id = p.instituicao_id
               WHERE p.ativo AND i.ativo ORDER BY p.id""",
        )
        metricas = _linhas(conexao, "SELECT codigo, descricao, unidade FROM metricas")
        # Todos os snapshots: a página escolhe o valor vigente em qualquer data.
        historico = _linhas(
            conexao,
            """SELECT s.perfil_id, s.metrica_codigo, s.data_referencia, s.valor, s.valor_texto,
                      s.periodo_inicio, s.periodo_fim
               FROM snapshots_metricas s
               JOIN perfis p ON p.id = s.perfil_id AND p.ativo
               JOIN instituicoes i ON i.id = p.instituicao_id AND i.ativo
               ORDER BY s.data_referencia, s.coletado_em""",
        )
        posts = _linhas(
            conexao,
            """SELECT perfil_id, data_publicacao, mes_publicacao, curtidas, curtidas_ocultas,
                      comentarios, tipo_midia, permalink
               FROM vw_instagram_posts ORDER BY data_publicacao""",
        )
        execucoes = _linhas(
            conexao,
            """SELECT coletor, status, iniciado_em, finalizado_em, perfis_ok, perfis_erro,
                      coalesce((detalhes->>'interrompida')::boolean, false)
               FROM execucoes ORDER BY iniciado_em""",
        )
    agora = datetime.now(FUSO_REFERENCIA)
    return {
        "gerado_em": agora.strftime("%d/%m/%Y %H:%M"),
        "gerado_iso": agora.isoformat(timespec="minutes"),
        "instituicoes": instituicoes,
        "perfis": perfis,
        "metricas": metricas,
        "historico": historico,
        "posts": posts,
        "execucoes": execucoes,
    }


def gerar_html(dados: dict[str, Any], origem: str) -> str:
    conteudo = json.dumps({**dados, "origem": origem}, ensure_ascii=False, separators=(",", ":"))
    # Impede que um texto do banco feche a tag <script> antes da hora.
    conteudo = conteudo.replace("</", "<\\/")
    return MODELO.read_text(encoding="utf-8").replace("/*__DADOS__*/null", conteudo)
