"""Rate-Limits für Login, zweiten Faktor, Passwort-Reset und Registrierung (A5), mit django-ratelimit.

Gezählt werden Fehlversuche je IP und je Konto in festen 15-Minuten-Fenstern. Ab dem 10. Fehlversuch
antwortet die App mit 429, ohne das Passwort oder den Code überhaupt zu prüfen.
"""

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django_ratelimit.core import get_usage

GRENZE = "10/15m"


def client_ip(request: HttpRequest) -> str:
    """Client-IP. Hinter Caddy (COCKPIT_HINTER_PROXY) zählt der letzte Eintrag von X-Forwarded-For."""
    if getattr(settings, "HINTER_PROXY", False):
        weitergeleitet = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if weitergeleitet:
            return weitergeleitet.split(",")[-1].strip()
    return str(request.META.get("REMOTE_ADDR", "unbekannt"))


def _zaehler(request: HttpRequest, gruppe: str, schluessel: str, erhoehen: bool) -> bool:
    nutzung = get_usage(request, group=gruppe, key=lambda _g, _r: schluessel, rate=GRENZE, increment=erhoehen)
    if nutzung is None:
        return False
    return int(nutzung["count"]) >= int(nutzung["limit"])


def _schluessel(request: HttpRequest, konto: str | None) -> list[tuple[str, str]]:
    paare = [("ip", f"ip:{client_ip(request)}")]
    if konto:
        paare.append(("konto", f"konto:{konto.strip().lower()}"))
    return paare


def gesperrt(request: HttpRequest, aktion: str, konto: str | None = None) -> bool:
    """True, wenn je IP oder je Konto bereits 10 Fehlversuche im aktuellen Fenster gezählt sind."""
    return any(_zaehler(request, f"{aktion}:{art}", wert, False) for art, wert in _schluessel(request, konto))


def fehlversuch(request: HttpRequest, aktion: str, konto: str | None = None) -> None:
    for art, wert in _schluessel(request, konto):
        _zaehler(request, f"{aktion}:{art}", wert, True)


def zu_viele_versuche(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/zu_viele_versuche.html", status=429)
