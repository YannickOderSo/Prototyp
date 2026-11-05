"""Zweistufige Anmeldung: Erst nach Passwort UND zweitem Faktor ruft die App `login()` auf.

Zwischen beiden Schritten steht nur die Nutzer-ID mit Zeitstempel in der Sitzung ("Vor-Login").
So ist `request.user` bis zur Bestätigung des zweiten Faktors anonym (A2, ADR-004).
"""

import time

from django.contrib.auth import login
from django.http import HttpRequest

from .models import Mitgliedschaft, Nutzer

VORLOGIN = "vorlogin_nutzer_id"
VORLOGIN_ZEIT = "vorlogin_zeit"
FIRMA = "firma_id"
ZWEITER_FAKTOR_OK = "zweiter_faktor_ok"
VORLOGIN_GUELTIG_SEKUNDEN = 10 * 60
BACKEND = "django.contrib.auth.backends.ModelBackend"


def vorlogin_setzen(request: HttpRequest, nutzer: Nutzer) -> None:
    request.session.cycle_key()
    request.session[VORLOGIN] = nutzer.pk
    request.session[VORLOGIN_ZEIT] = time.time()


def vorlogin_nutzer(request: HttpRequest) -> Nutzer | None:
    nutzer_id = request.session.get(VORLOGIN)
    zeit = request.session.get(VORLOGIN_ZEIT, 0)
    if not nutzer_id or time.time() - float(zeit) > VORLOGIN_GUELTIG_SEKUNDEN:
        return None
    return Nutzer.objects.filter(pk=nutzer_id, is_active=True).first()


def vorlogin_beenden(request: HttpRequest) -> None:
    request.session.pop(VORLOGIN, None)
    request.session.pop(VORLOGIN_ZEIT, None)


def anmeldung_abschliessen(request: HttpRequest, nutzer: Nutzer) -> None:
    """Nur aufrufen, nachdem Passwort und zweiter Faktor geprüft sind."""
    vorlogin_beenden(request)
    login(request, nutzer, backend=BACKEND)
    request.session[ZWEITER_FAKTOR_OK] = True
    erste = Mitgliedschaft.objects.filter(nutzer=nutzer).order_by("erstellt").first()
    if erste is not None:
        request.session[FIRMA] = erste.firma_id
