from django.contrib import messages
from django.contrib.auth import authenticate, logout
from django.contrib.auth.decorators import login_not_required
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from audit.services import protokolliere

from .anmeldung import FIRMA, anmeldung_abschliessen, vorlogin_setzen
from .forms import AnmeldeForm, NeuesKontoForm, RegistrierungsForm, TeamEinladungsForm
from .models import Mitgliedschaft, Nutzer, TeamEinladung, Zustimmung
from .rechte import nur_inhaber
from .services import (
    EinladungUngueltig,
    Registrierung,
    registrieren,
    team_einladen,
    team_einladung_annehmen,
    team_einladung_finden,
)
from .typen import FirmaRequest


def _sicheres_ziel(request: HttpRequest, ziel: str | None) -> str:
    if ziel and url_has_allowed_host_and_scheme(ziel, allowed_hosts={request.get_host()}, require_https=False):
        return ziel
    return reverse("web:start")


def nach_passwort(request: HttpRequest, nutzer: Nutzer, ziel: str | None = None) -> HttpResponseRedirect:
    """Nach erfolgreicher Passwortprüfung: weiter zum zweiten Faktor (Einrichtung oder Abfrage)."""
    vorlogin_setzen(request, nutzer)
    if ziel:
        request.session["anmeldung_ziel"] = ziel
    return _weiter_zum_zweiten_faktor(request, nutzer)


def _weiter_zum_zweiten_faktor(request: HttpRequest, nutzer: Nutzer) -> HttpResponseRedirect:
    # Ab M1-02 übernimmt hier die Zwei-Faktor-Anmeldung.
    anmeldung_abschliessen(request, nutzer)
    return redirect(_sicheres_ziel(request, request.session.pop("anmeldung_ziel", None)))


@login_not_required
def anmelden(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:start")
    form = AnmeldeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        nutzer = authenticate(request, email=form.cleaned_data["email"].lower(), password=form.cleaned_data["passwort"])
        if isinstance(nutzer, Nutzer):
            return nach_passwort(request, nutzer, request.GET.get("next"))
        form.add_error(None, "E-Mail-Adresse oder Passwort stimmen nicht.")
    return render(request, "accounts/anmelden.html", {"form": form})


@require_POST
def abmelden(request: HttpRequest) -> HttpResponse:
    logout(request)
    messages.info(request, "Sie sind abgemeldet.")
    return redirect("accounts:login")


@login_not_required
def registrierung(request: HttpRequest) -> HttpResponse:
    form = RegistrierungsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        daten = form.cleaned_data
        try:
            nutzer, _ = registrieren(
                Registrierung(
                    firmenname=daten["firmenname"],
                    name=daten["name"],
                    email=daten["email"],
                    passwort=daten["passwort"],
                    einladungscode=daten["einladungscode"],
                )
            )
        except EinladungUngueltig as fehler:
            form.add_error("einladungscode", str(fehler))
        except IntegrityError:
            form.add_error("email", "Zu dieser E-Mail-Adresse gibt es bereits ein Konto.")
        else:
            messages.success(request, "Ihr Konto ist angelegt. Richten Sie jetzt die Zwei-Faktor-Anmeldung ein.")
            return nach_passwort(request, nutzer)
    return render(request, "accounts/registrieren.html", {"form": form})


@require_POST
def firma_wechseln(request: FirmaRequest) -> HttpResponse:
    firma_id = request.POST.get("firma_id", "")
    if firma_id.isdigit() and Mitgliedschaft.objects.filter(nutzer=request.user, firma_id=int(firma_id)).exists():
        request.session[FIRMA] = int(firma_id)
    return redirect("web:start")


@nur_inhaber
def team(request: FirmaRequest) -> HttpResponse:
    firma = request.firma
    form = TeamEinladungsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].lower()
        if Mitgliedschaft.objects.filter(firma=firma, nutzer__email=email).exists():
            form.add_error("email", "Diese Person gehört bereits zu Ihrer Firma.")
        else:
            team_einladen(firma, request.user, email, form.cleaned_data["rolle"])
            messages.success(request, f"Einladung an {email} versendet.")
            return redirect("accounts:team")
    return render(
        request,
        "accounts/team.html",
        {
            "form": form,
            "mitglieder": Mitgliedschaft.objects.filter(firma=firma).select_related("nutzer").order_by("erstellt"),
            "offen": TeamEinladung.objects.filter(firma=firma, angenommen_am__isnull=True).order_by("-erstellt"),
        },
    )


@login_not_required
def team_annehmen(request: HttpRequest, token: str) -> HttpResponse:
    einladung = team_einladung_finden(token)
    if einladung is None:
        return render(request, "accounts/einladung_ungueltig.html", status=404)
    if request.user.is_authenticated:
        if request.user.email != einladung.email:
            messages.error(request, "Diese Einladung gilt für eine andere E-Mail-Adresse.")
            return redirect("web:start")
        if request.method == "POST":
            mitgliedschaft = team_einladung_annehmen(einladung, request.user)
            request.session[FIRMA] = mitgliedschaft.firma_id
            messages.success(request, f"Sie sind jetzt Mitglied bei {einladung.firma.name}.")
            return redirect("web:start")
        return render(request, "accounts/einladung_annehmen.html", {"einladung": einladung})
    if Nutzer.objects.filter(email=einladung.email).exists():
        messages.info(request, "Bitte melden Sie sich an, um die Einladung anzunehmen.")
        return redirect(f"{reverse('accounts:login')}?next={request.path}")
    form = NeuesKontoForm(request.POST or None, email=einladung.email)
    if request.method == "POST" and form.is_valid():
        nutzer = Nutzer.objects.create_user(
            email=einladung.email, password=form.cleaned_data["passwort"], name=form.cleaned_data["name"]
        )
        from web.rechtstexte import zustimmungspflichtig

        for text in zustimmungspflichtig():
            Zustimmung.objects.create(nutzer=nutzer, dokument=text.slug, version=text.version)
        team_einladung_annehmen(einladung, nutzer)
        protokolliere(einladung.firma, "konto.angelegt", nutzer=nutzer, objekt=nutzer)
        return nach_passwort(request, nutzer)
    return render(request, "accounts/einladung_neues_konto.html", {"form": form, "einladung": einladung})
