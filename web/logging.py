"""Strukturierte Logs als JSON. Keine personenbezogenen Inhalte, nur IDs."""

import json
import logging
from datetime import UTC, datetime

_STANDARD = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        daten: dict[str, object] = {
            "zeit": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "stufe": record.levelname,
            "logger": record.name,
            "nachricht": record.getMessage(),
        }
        for schluessel, wert in record.__dict__.items():
            if schluessel not in _STANDARD and not schluessel.startswith("_"):
                daten[schluessel] = wert if isinstance(wert, str | int | float | bool | None) else str(wert)
        if record.exc_info:
            daten["fehler"] = self.formatException(record.exc_info)
        return json.dumps(daten, ensure_ascii=False)
