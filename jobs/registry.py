"""Verzeichnis der Job-Typen und der Zeitplan-Einträge.

Apps melden ihre Jobs in einem Modul `aufgaben.py` an; die Jobs-App lädt diese Module beim Start.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Job

Handler = Callable[["Job"], None]

_HANDLER: dict[str, Handler] = {}


@dataclass(frozen=True)
class ZeitplanEintrag:
    name: str
    cron: str
    typ: str
    max_versuche: int = 3


_ZEITPLAN: dict[str, ZeitplanEintrag] = {}


def job(typ: str) -> Callable[[Handler], Handler]:
    """Dekorator: registriert eine Funktion als Handler für einen Job-Typ."""

    def registrieren(funktion: Handler) -> Handler:
        if typ in _HANDLER and _HANDLER[typ] is not funktion:
            raise ValueError(f"Job-Typ {typ} ist doppelt registriert")
        _HANDLER[typ] = funktion
        return funktion

    return registrieren


def handler_fuer(typ: str) -> Handler | None:
    return _HANDLER.get(typ)


def zeitplan(name: str, cron: str, typ: str, max_versuche: int = 3) -> None:
    """Registriert einen wiederkehrenden Job. `cron` ist ein 5-Feld-Ausdruck in Europe/Berlin."""
    from .cron import Cron

    Cron(cron)  # früh validieren
    _ZEITPLAN[name] = ZeitplanEintrag(name=name, cron=cron, typ=typ, max_versuche=max_versuche)


def zeitplan_eintraege() -> list[ZeitplanEintrag]:
    return list(_ZEITPLAN.values())
