"""Kontext für alle Seiten: Navigation (nur vorhandene Seiten) und Rechtstexte für den Fuß.

Desktop: Seitenleiste mit allen Punkten. Handy: untere Leiste mit höchstens vier Hauptzielen und „Mehr“ für den Rest
(Material-Empfehlung: drei bis fünf Ziele in der unteren Navigation).
"""

from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse

from .rechtstexte import RECHTSTEXTE

# (URL-Name, Titel, Kurztitel fürs Handy, Icon, nur für Rollen, die freigeben dürfen)
NAVIGATION = [
    ("web:start", "Cockpit", "Cockpit", "layout-dashboard", False),
    ("capture:liste", "Angebote & Rechnungen", "Belege", "file-pen-line", False),
    ("ledger:posten", "Offene Posten", "Posten", "receipt-text", False),
    ("ledger:kunden", "Kunden", "Kunden", "users", False),
    ("dunning:freigabe", "Mahnungen", "Mahnungen", "send", True),
    ("telefon:rueckrufe", "Rückrufe", "Rückrufe", "phone-incoming", False),
    ("reports:uebersicht", "Statistik", "Statistik", "chart-column", True),
    ("web:einstellungen", "Einstellungen", "Einstellungen", "settings", False),
]
# Reihenfolge der Hauptziele in der unteren Leiste; fehlt eines (Rolle), rückt das nächste nach
HANDY_HAUPTZIELE = ["web:start", "ledger:posten", "capture:liste", "dunning:freigabe", "ledger:kunden"]
HANDY_MAX = 4


def _zaehler(request: HttpRequest, darf_freigeben: bool) -> dict[str, int]:
    """Kleine Zähler an der Navigation: offene Freigaben und Entwürfe zur Prüfung."""
    from capture.models import Erfassung
    from dunning.models import Mahnvorschlag

    firma = request.firma  # type: ignore[attr-defined]
    from telefon.models import Rueckruf

    zaehler = {
        "capture:liste": Erfassung.objects.fuer(firma).filter(status=Erfassung.Status.PRUEFUNG).count(),
        "telefon:rueckrufe": Rueckruf.objects.fuer(firma).filter(status=Rueckruf.Status.OFFEN, test=False).count(),
    }
    if darf_freigeben:
        from dunning.models import Angebotserinnerung

        zaehler["dunning:freigabe"] = (
            Mahnvorschlag.objects.fuer(firma).filter(status=Mahnvorschlag.Status.VORGESCHLAGEN).count()
            + Angebotserinnerung.objects.fuer(firma).filter(status=Angebotserinnerung.Status.VORGESCHLAGEN).count()
        )
    return zaehler


def seite(request: HttpRequest) -> dict[str, object]:
    punkte: list[dict[str, object]] = []
    if getattr(request, "user", None) is not None and request.user.is_authenticated and getattr(request, "firma", None):
        darf_freigeben = getattr(request, "darf_freigeben", False)
        zaehler = _zaehler(request, darf_freigeben)
        for name, titel, kurz, icon, nur_freigabe in NAVIGATION:
            if nur_freigabe and not darf_freigeben:
                continue
            try:
                url = reverse(name)
            except NoReverseMatch:
                continue
            punkte.append(
                {"name": name, "url": url, "titel": titel, "kurz": kurz, "icon": icon, "aktiv": False}
                | ({"zahl": zaehler[name]} if zaehler.get(name) else {})
            )
        # aktiv ist der Punkt mit dem längsten passenden Pfad-Präfix
        passend = [
            p
            for p in punkte
            if request.path == p["url"] or (p["url"] != "/" and request.path.startswith(str(p["url"])))
        ]
        if passend:
            max(passend, key=lambda p: len(str(p["url"])))["aktiv"] = True
    nach_name = {p["name"]: p for p in punkte}
    haupt = [nach_name[n] for n in HANDY_HAUPTZIELE if n in nach_name][:HANDY_MAX]
    mehr = [p for p in punkte if p not in haupt]
    return {
        "navigation": punkte,
        "navigation_handy": haupt,
        "navigation_mehr": mehr,
        "navigation_mehr_aktiv": any(p["aktiv"] for p in mehr),
        "rechtstexte": RECHTSTEXTE,
    }
