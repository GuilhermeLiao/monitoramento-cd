"""Métricas do painel do Reclame Aqui que ainda não estavam no catálogo

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

metricas = sa.table(
    "metricas",
    sa.column("codigo", sa.Text),
    sa.column("descricao", sa.Text),
    sa.column("unidade", sa.Text),
    sa.column("plataforma_codigo", sa.Text),
)

METRICAS = [
    ("aguardando_resposta", "Reclamações aguardando resposta", "contagem", "reclame_aqui"),
    ("reclamacoes_avaliadas", "Reclamações avaliadas pelo consumidor", "contagem", "reclame_aqui"),
    ("nota_reclame_aqui", "Nota de reputação do Reclame Aqui (0 a 10)", "nota", "reclame_aqui"),
]


def upgrade() -> None:
    op.bulk_insert(
        metricas,
        [
            dict(zip(("codigo", "descricao", "unidade", "plataforma_codigo"), linha))
            for linha in METRICAS
        ],
    )


def downgrade() -> None:
    op.execute(metricas.delete().where(metricas.c.codigo.in_([m[0] for m in METRICAS])))
