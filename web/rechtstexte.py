"""Rechtstexte (F5). Inhalte liefert das Team; bis dahin zeigt die App deutlich markierte Platzhalter.

Jeder Text hat eine Version. Bei der Registrierung wird die Zustimmung zur jeweils aktuellen Version
der zustimmungspflichtigen Texte gespeichert.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rechtstext:
    slug: str
    titel: str
    version: str
    platzhalter: bool
    zustimmungspflichtig: bool


RECHTSTEXTE = [
    Rechtstext("impressum", "Impressum", "0-platzhalter", True, False),
    Rechtstext("datenschutz", "Datenschutz", "0-platzhalter", True, True),
    Rechtstext("agb", "AGB", "0-platzhalter", True, True),
    Rechtstext("avv", "AVV", "0-platzhalter", True, True),
]


def rechtstext(slug: str) -> Rechtstext | None:
    return next((t for t in RECHTSTEXTE if t.slug == slug), None)


def zustimmungspflichtig() -> list[Rechtstext]:
    return [t for t in RECHTSTEXTE if t.zustimmungspflichtig]
