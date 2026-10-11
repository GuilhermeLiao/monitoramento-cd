from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

FUSO_REFERENCIA = ZoneInfo("America/Sao_Paulo")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    # Só "dev" libera os testes de banco; o padrão é o mais restritivo.
    ambiente: str = "producao"
    # Schema alternativo (usado pelos testes para não tocar no public).
    db_schema: str | None = None
    config_path: Path = Path("config/instituicoes.yaml")
    log_level: str = "INFO"

    @property
    def sqlalchemy_url(self) -> str:
        """Força o driver psycopg 3, qualquer que seja o prefixo vindo do Neon."""
        url = self.database_url.strip()
        for prefixo in ("postgresql+psycopg://", "postgresql://", "postgres://"):
            if url.startswith(prefixo):
                return "postgresql+psycopg://" + url[len(prefixo) :]
        raise ValueError("DATABASE_URL precisa começar com postgresql://")


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
