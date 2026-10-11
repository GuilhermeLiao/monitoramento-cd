"""Modelos SQLAlchemy. O esquema real é criado pelas migrações em migrations/versions;
ao mudar um modelo aqui, crie a migração correspondente."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TIPOS_PLATAFORMA = ("loja_app", "avaliacao", "rede_social", "regulador")
STATUS_EXECUCAO = ("em_andamento", "sucesso", "parcial", "erro")

Pk = Annotated[int, mapped_column(BigInteger, Identity(), primary_key=True)]
Agora = Annotated[datetime, mapped_column(server_default=func.now())]
Json = Annotated[dict[str, Any], mapped_column(JSONB, server_default=text("'{}'::jsonb"))]


def _fk(alvo: str) -> Any:
    return mapped_column(BigInteger, ForeignKey(alvo))


def _em(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class Base(DeclarativeBase):
    type_annotation_map = {
        str: Text,
        datetime: DateTime(timezone=True),
        Decimal: Numeric,
    }


class Instituicao(Base):
    __tablename__ = "instituicoes"

    id: Mapped[Pk]
    nome: Mapped[str]
    nome_curto: Mapped[str] = mapped_column(unique=True)
    cnpj: Mapped[str | None] = mapped_column(unique=True)
    segmento: Mapped[str | None]
    ativo: Mapped[bool] = mapped_column(server_default=text("true"))
    criado_em: Mapped[Agora]


class Plataforma(Base):
    __tablename__ = "plataformas"
    __table_args__ = (
        CheckConstraint(f"tipo IN ({_em(TIPOS_PLATAFORMA)})", name="ck_plataformas_tipo"),
    )

    codigo: Mapped[str] = mapped_column(primary_key=True)
    nome: Mapped[str]
    tipo: Mapped[str]


class Perfil(Base):
    __tablename__ = "perfis"
    __table_args__ = (
        UniqueConstraint("plataforma_codigo", "identificador", name="uq_perfis_plataforma_identificador"),
        Index("ix_perfis_instituicao", "instituicao_id"),
    )

    id: Mapped[Pk]
    instituicao_id: Mapped[int] = _fk("instituicoes.id")
    plataforma_codigo: Mapped[str] = mapped_column(ForeignKey("plataformas.codigo"))
    identificador: Mapped[str]
    rotulo: Mapped[str | None]
    ativo: Mapped[bool] = mapped_column(server_default=text("true"))
    metadados: Mapped[Json]


class Metrica(Base):
    __tablename__ = "metricas"

    codigo: Mapped[str] = mapped_column(primary_key=True)
    descricao: Mapped[str]
    unidade: Mapped[str]
    plataforma_codigo: Mapped[str | None] = mapped_column(ForeignKey("plataformas.codigo"))


class Execucao(Base):
    __tablename__ = "execucoes"
    __table_args__ = (
        CheckConstraint(f"status IN ({_em(STATUS_EXECUCAO)})", name="ck_execucoes_status"),
        Index("ix_execucoes_iniciado_em", "iniciado_em"),
    )

    id: Mapped[Pk]
    coletor: Mapped[str]
    iniciado_em: Mapped[Agora]
    finalizado_em: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default=text("'em_andamento'"))
    perfis_ok: Mapped[int] = mapped_column(server_default=text("0"))
    perfis_erro: Mapped[int] = mapped_column(server_default=text("0"))
    detalhes: Mapped[Json]


class SnapshotMetrica(Base):
    __tablename__ = "snapshots_metricas"
    __table_args__ = (
        UniqueConstraint(
            "perfil_id",
            "metrica_codigo",
            "data_referencia",
            "periodo_inicio",
            "periodo_fim",
            name="uq_snapshots_metricas_chave",
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_snapshots_metricas_perfil_data", "perfil_id", "data_referencia"),
    )

    id: Mapped[Pk]
    execucao_id: Mapped[int] = _fk("execucoes.id")
    perfil_id: Mapped[int] = _fk("perfis.id")
    metrica_codigo: Mapped[str] = mapped_column(ForeignKey("metricas.codigo"))
    coletado_em: Mapped[Agora]
    data_referencia: Mapped[date]
    periodo_inicio: Mapped[date | None]
    periodo_fim: Mapped[date | None]
    valor: Mapped[Decimal | None]
    valor_texto: Mapped[str | None]


class RespostaBruta(Base):
    __tablename__ = "respostas_brutas"
    __table_args__ = (Index("ix_respostas_brutas_coletado_em", "coletado_em"),)

    id: Mapped[Pk]
    execucao_id: Mapped[int] = _fk("execucoes.id")
    perfil_id: Mapped[int] = _fk("perfis.id")
    coletado_em: Mapped[Agora]
    origem: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ArquivoProcessado(Base):
    __tablename__ = "arquivos_processados"
    __table_args__ = (
        UniqueConstraint("fonte", "hash_sha256", name="uq_arquivos_processados_fonte_hash"),
    )

    id: Mapped[Pk]
    fonte: Mapped[str]
    nome_arquivo: Mapped[str]
    mes_referencia: Mapped[date | None]
    hash_sha256: Mapped[str]
    linhas_lidas: Mapped[int]
    linhas_gravadas: Mapped[int]
    processado_em: Mapped[Agora]


class ReclamacaoConsumidorGov(Base):
    __tablename__ = "reclamacoes_consumidor_gov"
    __table_args__ = (
        CheckConstraint(
            "nota_consumidor BETWEEN 1 AND 5", name="ck_reclamacoes_consumidor_gov_nota"
        ),
        Index("ix_reclamacoes_consumidor_gov_perfil_finalizacao", "perfil_id", "data_finalizacao"),
    )

    id: Mapped[Pk]
    perfil_id: Mapped[int] = _fk("perfis.id")
    chave_origem: Mapped[str] = mapped_column(unique=True)
    data_abertura: Mapped[date | None]
    data_finalizacao: Mapped[date | None]
    mes_referencia: Mapped[date | None]
    segmento: Mapped[str | None]
    area: Mapped[str | None]
    assunto: Mapped[str | None]
    grupo_problema: Mapped[str | None]
    problema: Mapped[str | None]
    como_comprou: Mapped[str | None]
    procurou_empresa: Mapped[bool | None]
    respondida: Mapped[bool | None]
    situacao: Mapped[str | None]
    avaliacao: Mapped[str | None]
    nota_consumidor: Mapped[int | None] = mapped_column(SmallInteger)
    tempo_resposta_dias: Mapped[int | None]
    uf: Mapped[str | None]
    regiao: Mapped[str | None]
    arquivo_id: Mapped[int | None] = _fk("arquivos_processados.id")


class ReclamacaoReclameAqui(Base):
    __tablename__ = "reclamacoes_reclame_aqui"
    __table_args__ = (
        UniqueConstraint("perfil_id", "id_externo", name="uq_reclamacoes_reclame_aqui_perfil_externo"),
        Index("ix_reclamacoes_reclame_aqui_perfil_criada", "perfil_id", "criada_em"),
    )

    id: Mapped[Pk]
    perfil_id: Mapped[int] = _fk("perfis.id")
    id_externo: Mapped[str]
    criada_em: Mapped[datetime | None]
    status: Mapped[str | None]
    categoria: Mapped[str | None]
    problema: Mapped[str | None]
    produto: Mapped[str | None]
    respondida: Mapped[bool | None]
    resolvida: Mapped[bool | None]
    nota_consumidor: Mapped[Decimal | None]
    voltaria_fazer_negocio: Mapped[bool | None]
    coletado_em: Mapped[Agora]


class PostInstagram(Base):
    __tablename__ = "posts_instagram"
    __table_args__ = (Index("ix_posts_instagram_perfil_publicado", "perfil_id", "publicado_em"),)

    id: Mapped[Pk]
    perfil_id: Mapped[int] = _fk("perfis.id")
    media_id: Mapped[str] = mapped_column(unique=True)
    publicado_em: Mapped[datetime]
    tipo_midia: Mapped[str | None]
    permalink: Mapped[str | None]


class SnapshotPostInstagram(Base):
    __tablename__ = "snapshots_posts_instagram"
    __table_args__ = (
        UniqueConstraint("post_id", "data_coleta", name="uq_snapshots_posts_instagram_post_data"),
    )

    id: Mapped[Pk]
    post_id: Mapped[int] = _fk("posts_instagram.id")
    execucao_id: Mapped[int] = _fk("execucoes.id")
    coletado_em: Mapped[Agora]
    # Dia da coleta no fuso America/Sao_Paulo; base da unicidade diária.
    data_coleta: Mapped[date]
    curtidas: Mapped[int | None]
    curtidas_ocultas: Mapped[bool] = mapped_column(server_default=text("false"))
    comentarios: Mapped[int | None]
    idade_post_dias: Mapped[int | None]
