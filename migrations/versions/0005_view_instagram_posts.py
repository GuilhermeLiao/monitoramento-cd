"""View com os posts do Instagram e a última contagem de curtidas

Revision ID: 0005
Revises: 0004
"""

from pathlib import Path

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ARQUIVO = Path(__file__).resolve().parents[2] / "sql" / "views" / "vw_instagram_posts.sql"


def upgrade() -> None:
    op.execute(ARQUIVO.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS vw_instagram_posts")
