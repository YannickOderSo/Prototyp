"""Views für den zweiten Faktor. Erst nach Bestätigung ruft die App `login()` auf (siehe anmeldung.py)."""

import segno
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.safestring import mark_safe

from audit.services import protokolliere

from . import totp
from .anmeldung import anmeldung_abschliessen, vorlogin_nutzer
from .models import Mitgliedschaft
from .typen import FirmaRequest
from .zweifaktor import (
    aktiver_zweiter_faktor,
    code_pruefen,
    einrichtung_beginnen,
    einrichtung_bestaetigen,
    geheimnis,
    neue_wiederherstellungscodes,
    wiederherstellungscode_einloesen,
)

CODES_ANZEIGEN = "wiederherstellungscodes_anzeigen"


class CodeForm(forms.Form):
    code = forms.CharField(
        label="Code aus der Authenticator-App",
        max_length=20,
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}),
    )


class PruefForm(forms.Form):
    code = forms.CharField(
        label="Code aus der Authenticator-App oder Wiederherstellungscode",
        max_length=20,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


def _ziel(request: HttpRequest) -> str:
    ziel = request.session.pop("anmeldung_ziel", None)
    if ziel and url_has_allowed_host_and_scheme(ziel, allowed_hosts={request.get_host()}):
        return str(ziel)
    return reverse("web:start")


def _protokollieren(nutzer_id: int, ereignis: str) -> None:
    for m in Mitgliedschaft.objects.filter(nutzer_id=nutzer_id).select_related("firma", "nutzer"):
        protokolliere(m.firma, ereignis, nutzer=m.nutzer)


@login_not_required
def einrichten(request: HttpRequest) -> HttpResponse:
    nutzer = vorlogin_nutzer(request)
    if nutzer is None:
        messages.error(request, "Bitte melden Sie sich erneut an.")
        return redirect("accounts:login")
    if aktiver_zweiter_faktor(nutzer) is not None:
        return redirect("accounts:zweiter_faktor")
    zf = einrichtung_beginnen(nutzer)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        codes = einrichtung_bestaetigen(zf, form.cleaned_data["code"])
        if codes is not None:
            anmeldung_abschliessen(request, nutzer)
            request.session[CODES_ANZEIGEN] = codes
            _protokollieren(nutzer.pk, "konto.zwei_faktor_eingerichtet")
            return redirect("accounts:wiederherstellungscodes")
        form.add_error(
            "code", "Der Code passt nicht. Bitte prüfen Sie die Uhrzeit Ihres Handys und versuchen Sie es erneut."
        )
    schluessel = geheimnis(zf)
    uri = totp.provisioning_uri(schluessel, nutzer.email)
    qr = mark_safe(segno.make(uri, error="m").svg_inline(scale=4, dark="#1c2430"))  # noqa: S308 – erzeugtes SVG
    gruppiert = " ".join(schluessel[i : i + 4] for i in range(0, len(schluessel), 4))
    return render(request, "accounts/zweifaktor_einrichten.html", {"form": form, "qr": qr, "schluessel": gruppiert})


@login_not_required
def pruefen(request: HttpRequest) -> HttpResponse:
    nutzer = vorlogin_nutzer(request)
    if nutzer is None:
        messages.error(request, "Bitte melden Sie sich erneut an.")
        return redirect("accounts:login")
    zf = aktiver_zweiter_faktor(nutzer)
    if zf is None:
        return redirect("accounts:zweiter_faktor_einrichten")
    form = PruefForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        eingabe = form.cleaned_data["code"].strip()
        if code_pruefen(zf, eingabe):
            anmeldung_abschliessen(request, nutzer)
            return redirect(_ziel(request))
        if wiederherstellungscode_einloesen(zf, eingabe):
            anmeldung_abschliessen(request, nutzer)
            _protokollieren(nutzer.pk, "konto.wiederherstellungscode_verwendet")
            rest = len(zf.wiederherstellungscodes_hash)
            messages.warning(request, f"Wiederherstellungscode verwendet. Noch {rest} Codes übrig.")
            return redirect(_ziel(request))
        form.add_error("code", "Der Code ist ungültig oder wurde bereits verwendet.")
        return render(request, "accounts/zweifaktor_pruefen.html", {"form": form}, status=200)
    return render(request, "accounts/zweifaktor_pruefen.html", {"form": form})


def wiederherstellungscodes(request: FirmaRequest) -> HttpResponse:
    codes = request.session.pop(CODES_ANZEIGEN, None)
    if not codes:
        return redirect("accounts:sicherheit")
    return render(request, "accounts/wiederherstellungscodes.html", {"codes": codes})


def sicherheit(request: FirmaRequest) -> HttpResponse:
    zf = aktiver_zweiter_faktor(request.user)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and zf is not None:
        if code_pruefen(zf, form.cleaned_data["code"]):
            request.session[CODES_ANZEIGEN] = neue_wiederherstellungscodes(zf)
            _protokollieren(request.user.pk, "konto.wiederherstellungscodes_erneuert")
            return redirect("accounts:wiederherstellungscodes")
        form.add_error("code", "Der Code passt nicht.")
    rest = len(zf.wiederherstellungscodes_hash) if zf else 0
    return render(request, "accounts/sicherheit.html", {"form": form, "rest": rest})
