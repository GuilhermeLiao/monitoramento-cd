"""Tabelas iniciais

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

AGORA = sa.text("now()")
JSON_VAZIO = sa.text("'{}'::jsonb")


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True)


def _fk(nome: str, alvo: str, nullable: bool = False) -> sa.Column:
    return sa.Column(nome, sa.BigInteger, sa.ForeignKey(alvo), nullable=nullable)


def _tz(nome: str, nullable: bool = False, agora: bool = False) -> sa.Column:
    return sa.Column(
        nome,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=AGORA if agora else None,
    )


def upgrade() -> None:
    op.create_table(
        "instituicoes",
        _id(),
        sa.Column("nome", sa.Text, nullable=False),
        sa.Column("nome_curto", sa.Text, nullable=False, unique=True),
        sa.Column("cnpj", sa.Text, unique=True),
        sa.Column("segmento", sa.Text),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        _tz("criado_em", agora=True),
    )

    op.create_table(
        "plataformas",
        sa.Column("codigo", sa.Text, primary_key=True),
        sa.Column("nome", sa.Text, nullable=False),
        sa.Column("tipo", sa.Text, nullable=False),
        sa.CheckConstraint(
            "tipo IN ('loja_app', 'avaliacao', 'rede_social', 'regulador')",
            name="ck_plataformas_tipo",
        ),
    )

    op.create_table(
        "perfis",
        _id(),
        _fk("instituicao_id", "instituicoes.id"),
        sa.Column(
            "plataforma_codigo", sa.Text, sa.ForeignKey("plataformas.codigo"), nullable=False
        ),
        sa.Column("identificador", sa.Text, nullable=False),
        sa.Column("rotulo", sa.Text),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("metadados", JSONB, nullable=False, server_default=JSON_VAZIO),
        sa.UniqueConstraint(
            "plataforma_codigo", "identificador", name="uq_perfis_plataforma_identificador"
        ),
    )
    op.create_index("ix_perfis_instituicao", "perfis", ["instituicao_id"])

    op.create_table(
        "metricas",
        sa.Column("codigo", sa.Text, primary_key=True),
        sa.Column("descricao", sa.Text, nullable=False),
        sa.Column("unidade", sa.Text, nullable=False),
        sa.Column("plataforma_codigo", sa.Text, sa.ForeignKey("plataformas.codigo")),
    )

    op.create_table(
        "execucoes",
        _id(),
        sa.Column("coletor", sa.Text, nullable=False),
        _tz("iniciado_em", agora=True),
        _tz("finalizado_em", nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'em_andamento'")),
        sa.Column("perfis_ok", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("perfis_erro", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("detalhes", JSONB, nullable=False, server_default=JSON_VAZIO),
        sa.CheckConstraint(
            "status IN ('em_andamento', 'sucesso', 'parcial', 'erro')",
            name="ck_execucoes_status",
        ),
    )
    op.create_index("ix_execucoes_iniciado_em", "execucoes", ["iniciado_em"])

    op.create_table(
        "snapshots_metricas",
        _id(),
        _fk("execucao_id", "execucoes.id"),
        _fk("perfil_id", "perfis.id"),
        sa.Column("metrica_codigo", sa.Text, sa.ForeignKey("metricas.codigo"), nullable=False),
        _tz("coletado_em", agora=True),
        sa.Column("data_referencia", sa.Date, nullable=False),
        sa.Column("periodo_inicio", sa.Date),
        sa.Column("periodo_fim", sa.Date),
        sa.Column("valor", sa.Numeric),
        sa.Column("valor_texto", sa.Text),
        sa.UniqueConstraint(
            "perfil_id",
            "metrica_codigo",
            "data_referencia",
            "periodo_inicio",
            "periodo_fim",
            name="uq_snapshots_metricas_chave",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_snapshots_metricas_perfil_data", "snapshots_metricas", ["perfil_id", "data_referencia"]
    )

    op.create_table(
        "respostas_brutas",
        _id(),
        _fk("execucao_id", "execucoes.id"),
        _fk("perfil_id", "perfis.id"),
        _tz("coletado_em", agora=True),
        sa.Column("origem", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False),
    )
    op.create_index("ix_respostas_brutas_coletado_em", "respostas_brutas", ["coletado_em"])

    op.create_table(
        "arquivos_processados",
        _id(),
        sa.Column("fonte", sa.Text, nullable=False),
        sa.Column("nome_arquivo", sa.Text, nullable=False),
        sa.Column("mes_referencia", sa.Date),
        sa.Column("hash_sha256", sa.Text, nullable=False),
        sa.Column("linhas_lidas", sa.Integer, nullable=False),
        sa.Column("linhas_gravadas", sa.Integer, nullable=False),
        _tz("processado_em", agora=True),
        sa.UniqueConstraint("fonte", "hash_sha256", name="uq_arquivos_processados_fonte_hash"),
    )

    op.create_table(
        "reclamacoes_consumidor_gov",
        _id(),
        _fk("perfil_id", "perfis.id"),
        sa.Column("chave_origem", sa.Text, nullable=False, unique=True),
        sa.Column("data_abertura", sa.Date),
        sa.Column("data_finalizacao", sa.Date),
        sa.Column("mes_referencia", sa.Date),
        sa.Column("segmento", sa.Text),
        sa.Column("area", sa.Text),
        sa.Column("assunto", sa.Text),
        sa.Column("grupo_problema", sa.Text),
        sa.Column("problema", sa.Text),
        sa.Column("como_comprou", sa.Text),
        sa.Column("procurou_empresa", sa.Boolean),
        sa.Column("respondida", sa.Boolean),
        sa.Column("situacao", sa.Text),
        sa.Column("avaliacao", sa.Text),
        sa.Column("nota_consumidor", sa.SmallInteger),
        sa.Column("tempo_resposta_dias", sa.Integer),
        sa.Column("uf", sa.Text),
        sa.Column("regiao", sa.Text),
        _fk("arquivo_id", "arquivos_processados.id", nullable=True),
        sa.CheckConstraint(
            "nota_consumidor BETWEEN 1 AND 5", name="ck_reclamacoes_consumidor_gov_nota"
        ),
    )
    op.create_index(
        "ix_reclamacoes_consumidor_gov_perfil_finalizacao",
        "reclamacoes_consumidor_gov",
        ["perfil_id", "data_finalizacao"],
    )

    op.create_table(
        "reclamacoes_reclame_aqui",
        _id(),
        _fk("perfil_id", "perfis.id"),
        sa.Column("id_externo", sa.Text, nullable=False),
        _tz("criada_em", nullable=True),
        sa.Column("status", sa.Text),
        sa.Column("categoria", sa.Text),
        sa.Column("problema", sa.Text),
        sa.Column("produto", sa.Text),
        sa.Column("respondida", sa.Boolean),
        sa.Column("resolvida", sa.Boolean),
        sa.Column("nota_consumidor", sa.Numeric),
        sa.Column("voltaria_fazer_negocio", sa.Boolean),
        _tz("coletado_em", agora=True),
        sa.UniqueConstraint(
            "perfil_id", "id_externo", name="uq_reclamacoes_reclame_aqui_perfil_externo"
        ),
    )
    op.create_index(
        "ix_reclamacoes_reclame_aqui_perfil_criada",
        "reclamacoes_reclame_aqui",
        ["perfil_id", "criada_em"],
    )

    op.create_table(
        "posts_instagram",
        _id(),
        _fk("perfil_id", "perfis.id"),
        sa.Column("media_id", sa.Text, nullable=False, unique=True),
        _tz("publicado_em"),
        sa.Column("tipo_midia", sa.Text),
        sa.Column("permalink", sa.Text),
    )
    op.create_index(
        "ix_posts_instagram_perfil_publicado", "posts_instagram", ["perfil_id", "publicado_em"]
    )

    op.create_table(
        "snapshots_posts_instagram",
        _id(),
        _fk("post_id", "posts_instagram.id"),
        _fk("execucao_id", "execucoes.id"),
        _tz("coletado_em", agora=True),
        sa.Column("data_coleta", sa.Date, nullable=False),
        sa.Column("curtidas", sa.Integer),
        sa.Column("curtidas_ocultas", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("comentarios", sa.Integer),
        sa.Column("idade_post_dias", sa.Integer),
        sa.UniqueConstraint(
            "post_id", "data_coleta", name="uq_snapshots_posts_instagram_post_data"
        ),
    )


def downgrade() -> None:
    for tabela in (
        "snapshots_posts_instagram",
        "posts_instagram",
        "reclamacoes_reclame_aqui",
        "reclamacoes_consumidor_gov",
        "arquivos_processados",
        "respostas_brutas",
        "snapshots_metricas",
        "execucoes",
        "metricas",
        "perfis",
        "plataformas",
        "instituicoes",
    ):
        op.drop_table(tabela)
