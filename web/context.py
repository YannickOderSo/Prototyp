"""Kontext für alle Seiten: Navigation (nur vorhandene Seiten) und Rechtstexte für den Fuß."""

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from .rechtstexte import RECHTSTEXTE

# (URL-Name, Titel, nur für Rollen, die freigeben dürfen)
NAVIGATION = [
    ("web:start", "Cockpit", False),
    ("ledger:posten", "Offene Posten", False),
    ("dunning:freigabe", "Mahnungen", True),
    ("capture:liste", "Erfassen", False),
    ("web:einstellungen", "Einstellungen", False),
]


def seite(request: HttpRequest) -> dict[str, object]:
    punkte = []
    if getattr(request, "user", None) is not None and request.user.is_authenticated and getattr(request, "firma", None):
        darf_freigeben = getattr(request, "darf_freigeben", False)
        for name, titel, nur_freigabe in NAVIGATION:
            if nur_freigabe and not darf_freigeben:
                continue
            try:
                url = reverse(name)
            except NoReverseMatch:
                continue
            aktiv = request.path == url if url == "/" else request.path.startswith(url)
            punkte.append({"url": url, "titel": titel, "aktiv": aktiv})
    return {"navigation": punkte, "rechtstexte": RECHTSTEXTE}
