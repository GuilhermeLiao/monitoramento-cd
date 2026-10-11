from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from monitor.settings import Settings, get_settings


def criar_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    connect_args: dict[str, str] = {}
    if settings.db_schema:
        # Exige conexão direta do Neon (o endpoint "-pooler" ignora este parâmetro).
        connect_args["options"] = f"-csearch_path={settings.db_schema}"
    # pool_pre_ping: o Neon suspende o compute quando ocioso e derruba conexões antigas.
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True, connect_args=connect_args)


def criar_fabrica_sessoes(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine or criar_engine(), expire_on_commit=False)
