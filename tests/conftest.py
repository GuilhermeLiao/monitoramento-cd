"""Fixtures de banco.

Os testes de banco só rodam com AMBIENTE=dev (no .env ou no ambiente) e usam um
schema temporário, criado e apagado a cada sessão do pytest. Nunca tocam no public.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from monitor.db.session import criar_engine
from monitor.settings import Settings

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def alembic_cfg() -> Config:
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    return cfg


@pytest.fixture(scope="session")
def engine(alembic_cfg: Config) -> Iterator[Engine]:
    try:
        settings = Settings(_env_file=RAIZ / ".env")  # type: ignore[call-arg]
    except ValidationError:
        pytest.skip("DATABASE_URL não definida")
    if settings.ambiente != "dev":
        pytest.skip("Testes de banco exigem AMBIENTE=dev e a DATABASE_URL do branch dev do Neon")

    schema = f"teste_{uuid.uuid4().hex[:12]}"
    admin = criar_engine(settings)
    with admin.begin() as conexao:
        conexao.execute(text(f'CREATE SCHEMA "{schema}"'))

    # As migrações (migrations/env.py) leem as mesmas variáveis de ambiente.
    os.environ["DATABASE_URL"] = settings.database_url
    os.environ["DB_SCHEMA"] = schema
    engine_teste = criar_engine(settings.model_copy(update={"db_schema": schema}))
    try:
        command.upgrade(alembic_cfg, "head")
        yield engine_teste
    finally:
        engine_teste.dispose()
        os.environ.pop("DB_SCHEMA", None)
        with admin.begin() as conexao:
            conexao.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def fabrica(engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(engine, expire_on_commit=False)
    # plataformas e metricas vêm da migração e são preservadas.
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "TRUNCATE instituicoes, execucoes, arquivos_processados "
                "RESTART IDENTITY CASCADE"
            )
        )
