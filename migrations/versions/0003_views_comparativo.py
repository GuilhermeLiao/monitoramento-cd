"""Views de comparativo para BI

Revision ID: 0003
Revises: 0002
"""

from pathlib import Path

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PASTA_VIEWS = Path(__file__).resolve().parents[2] / "sql" / "views"
VIEWS = ["vw_metricas_atuais", "vw_metricas_mensais", "vw_consumidor_gov_periodo"]


def upgrade() -> None:
    for view in VIEWS:
        op.execute((PASTA_VIEWS / f"{view}.sql").read_text(encoding="utf-8"))


def downgrade() -> None:
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {view}")
