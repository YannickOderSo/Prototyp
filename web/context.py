"""Kontext für alle Seiten: Navigation (nur vorhandene Seiten) und Rechtstexte für den Fuß."""

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from .rechtstexte import RECHTSTEXTE

# (URL-Name, Titel, nur für Rollen, die freigeben dürfen)
NAVIGATION = [
    ("web:start", "Cockpit", False),
    ("ledger:posten", "Offene Posten", False),
    ("ledger:kunden", "Kunden", False),
    ("dunning:freigabe", "Mahnungen", True),
    ("capture:liste", "Erfassen", False),
    ("reports:uebersicht", "Berichte", True),
    ("web:einstellungen", "Einstellungen", False),
]


def seite(request: HttpRequest) -> dict[str, object]:
    punkte: list[dict[str, str | bool]] = []
    if getattr(request, "user", None) is not None and request.user.is_authenticated and getattr(request, "firma", None):
        darf_freigeben = getattr(request, "darf_freigeben", False)
        for name, titel, nur_freigabe in NAVIGATION:
            if nur_freigabe and not darf_freigeben:
                continue
            try:
                url = reverse(name)
            except NoReverseMatch:
                continue
            punkte.append({"url": url, "titel": titel, "aktiv": False})
        # aktiv ist der Punkt mit dem längsten passenden Pfad-Präfix
        passend = [
            p
            for p in punkte
            if request.path == p["url"] or (p["url"] != "/" and request.path.startswith(str(p["url"])))
        ]
        if passend:
            max(passend, key=lambda p: len(str(p["url"])))["aktiv"] = True
    return {"navigation": punkte, "rechtstexte": RECHTSTEXTE}
