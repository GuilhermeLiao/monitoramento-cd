import json
import logging
import sys
from datetime import UTC, datetime

_ATRIBUTOS_PADRAO = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class FormatadorJson(logging.Formatter):
    """Uma linha JSON por evento; campos passados em `extra=` viram chaves."""

    def format(self, record: logging.LogRecord) -> str:
        evento = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _ATRIBUTOS_PADRAO:
                evento[chave] = valor
        if record.exc_info:
            evento["excecao"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logging(nivel: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(FormatadorJson())
    raiz = logging.getLogger()
    raiz.handlers[:] = [handler]
    raiz.setLevel(nivel.upper())
