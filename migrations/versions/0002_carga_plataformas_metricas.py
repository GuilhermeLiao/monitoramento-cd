"""Carga de plataformas e do catálogo de métricas

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

plataformas = sa.table(
    "plataformas", sa.column("codigo", sa.Text), sa.column("nome", sa.Text), sa.column("tipo", sa.Text)
)
metricas = sa.table(
    "metricas",
    sa.column("codigo", sa.Text),
    sa.column("descricao", sa.Text),
    sa.column("unidade", sa.Text),
    sa.column("plataforma_codigo", sa.Text),
)

PLATAFORMAS = [
    ("app_store", "App Store", "loja_app"),
    ("google_play", "Google Play", "loja_app"),
    ("reclame_aqui", "Reclame Aqui", "avaliacao"),
    ("consumidor_gov", "Consumidor.gov.br", "regulador"),
    ("instagram", "Instagram", "rede_social"),
]

# Convenção: pct_* em escala 0-100; durações trazem a unidade no nome.
METRICAS = [
    ("nota_media", "Nota média das avaliações", "nota", None),
    ("total_avaliacoes", "Quantidade de avaliações", "contagem", None),
    ("seguidores", "Número de seguidores", "contagem", None),
    ("posts_periodo", "Posts publicados no período", "contagem", None),
    ("total_reclamacoes", "Total de reclamações no período", "contagem", None),
    ("pct_respondidas", "Reclamações respondidas", "percentual", None),
    ("pct_resolvidas", "Reclamações resolvidas", "percentual", None),
    ("nota_consumidor", "Nota dada pelo consumidor", "nota", None),
    ("tempo_resposta_dias", "Tempo médio de resposta", "dias", None),
    ("pct_voltaria_negocio", "Voltaria a fazer negócio", "percentual", "reclame_aqui"),
    ("status_reputacao", "Status de reputação (em valor_texto)", "categoria", "reclame_aqui"),
]


def upgrade() -> None:
    op.bulk_insert(
        plataformas, [dict(zip(("codigo", "nome", "tipo"), linha)) for linha in PLATAFORMAS]
    )
    op.bulk_insert(
        metricas,
        [
            dict(zip(("codigo", "descricao", "unidade", "plataforma_codigo"), linha))
            for linha in METRICAS
        ],
    )


def downgrade() -> None:
    op.execute(metricas.delete().where(metricas.c.codigo.in_([m[0] for m in METRICAS])))
    op.execute(plataformas.delete().where(plataformas.c.codigo.in_([p[0] for p in PLATAFORMAS])))
