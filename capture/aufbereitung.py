"""Textaufbereitung je Dateiart (M3-04 ergänzt PDF, CSV-Zeiterfassung und Mail)."""

from __future__ import annotations

from .dateien import lesen
from .models import Datei


def _text(daten: bytes) -> str:
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            return daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return daten.decode("utf-8", errors="replace")


def aufbereiten_datei(datei: Datei) -> str:
    if datei.art == Datei.Art.TEXT:
        return f"### Notiz „{datei.name}“\n{_text(lesen(datei)).strip()}\n"
    return ""
