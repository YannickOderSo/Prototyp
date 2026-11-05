"""M1-01: Registrierung nur mit Einladungscode (A1), Login mit E-Mail, Rollen, Team-Einladungen."""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from accounts.codes import code_hash, normalisiere
from accounts.models import Einladung, Firma, Mitgliedschaft, Nutzer, Rolle, TeamEinladung, Zustimmung
from accounts.services import einladung_erstellen
from audit.models import Protokolleintrag
from tests.conftest import PASSWORT
from web.rechtstexte import zustimmungspflichtig


def _formular(code, email="neu@betrieb.example", **extra):
    daten = {
        "einladungscode": code,
        "firmenname": "Dachdeckerei Neu",
        "name": "Nora Neu",
        "email": email,
        "passwort": PASSWORT,
        "passwort2": PASSWORT,
    }
    for text in zustimmungspflichtig():
        daten[f"zustimmung_{text.slug}"] = "on"
    daten.update(extra)
    return daten


@pytest.mark.django_db
def test_registrierung_mit_gueltigem_code_legt_firma_inhaber_und_zustimmungen_an(client):
    code = einladung_erstellen()
    antwort = client.post(reverse("accounts:registrieren"), _formular(code.lower()))
    assert antwort.status_code == 302
    nutzer = Nutzer.objects.get(email="neu@betrieb.example")
    firma = Firma.objects.get(name="Dachdeckerei Neu")
    assert Mitgliedschaft.objects.get(nutzer=nutzer).rolle == Rolle.INHABER
    assert Mitgliedschaft.objects.get(nutzer=nutzer).firma == firma
    assert Zustimmung.objects.filter(nutzer=nutzer).count() == len(zustimmungspflichtig())
    einladung = Einladung.objects.get(code_hash=code_hash(code))
    assert einladung.verwendet_am is not None
    assert einladung.verwendet_von == firma
    assert Protokolleintrag.objects.filter(firma=firma, ereignis="konto.registriert").exists()


@pytest.mark.django_db
def test_ohne_code_keine_registrierung(client):
    antwort = client.post(reverse("accounts:registrieren"), _formular("FALS-CHER-CODE-1234"))
    assert antwort.status_code == 200
    assert "Einladungscode ist ungültig" in antwort.content.decode()
    assert not Nutzer.objects.exists()
    assert not Firma.objects.exists()


@pytest.mark.django_db
def test_code_ist_nur_einmal_verwendbar(client):
    code = einladung_erstellen()
    client.post(reverse("accounts:registrieren"), _formular(code))
    client.logout()
    antwort = client.post(reverse("accounts:registrieren"), _formular(code, email="zweiter@betrieb.example"))
    assert antwort.status_code == 200
    assert not Nutzer.objects.filter(email="zweiter@betrieb.example").exists()
    assert Firma.objects.count() == 1


@pytest.mark.django_db
def test_abgelaufener_code_wird_abgelehnt(client):
    code = einladung_erstellen(gueltig_tage=1)
    Einladung.objects.filter(code_hash=code_hash(code)).update(gueltig_bis=timezone.now() - timedelta(seconds=1))
    antwort = client.post(reverse("accounts:registrieren"), _formular(code))
    assert antwort.status_code == 200
    assert not Nutzer.objects.exists()


@pytest.mark.django_db
def test_zustimmung_zu_rechtstexten_ist_pflicht(client):
    code = einladung_erstellen()
    daten = _formular(code)
    for text in zustimmungspflichtig():
        daten.pop(f"zustimmung_{text.slug}")
    antwort = client.post(reverse("accounts:registrieren"), daten)
    assert antwort.status_code == 200
    assert not Nutzer.objects.exists()
    assert Einladung.objects.get().verwendet_am is None


@pytest.mark.django_db
def test_doppelte_email_und_schwaches_passwort_werden_abgelehnt(client, inhaber):
    code = einladung_erstellen()
    antwort = client.post(reverse("accounts:registrieren"), _formular(code, email="INHABER@muster.example"))
    assert "bereits ein Konto" in antwort.content.decode()
    antwort = client.post(reverse("accounts:registrieren"), _formular(code, passwort="kurz", passwort2="kurz"))
    assert antwort.status_code == 200
    assert Einladung.objects.get().verwendet_am is None


@pytest.mark.django_db
def test_codes_werden_nur_als_hash_gespeichert():
    code = einladung_erstellen()
    einladung = Einladung.objects.get()
    assert normalisiere(code) not in einladung.code_hash
    assert len(einladung.code_hash) == 64


@pytest.mark.django_db
def test_kommando_einladung_erstellen(capsys):
    call_command("einladung_erstellen", "--anzahl", "2", "--notiz", "Pilot")
    zeilen = capsys.readouterr().out.strip().splitlines()
    assert len(zeilen) == 2
    assert Einladung.objects.filter(notiz="Pilot").count() == 2


def test_seiten_ohne_anmeldung_leiten_zum_login(client, db):
    antwort = client.get(reverse("web:start"))
    assert antwort.status_code == 302
    assert antwort["Location"].startswith(reverse("accounts:login"))


@pytest.mark.django_db
def test_rechtstexte_und_login_sind_oeffentlich(client):
    assert client.get(reverse("accounts:login")).status_code == 200
    assert client.get(reverse("accounts:registrieren")).status_code == 200
    assert client.get(reverse("web:rechtstext", args=["impressum"])).status_code == 200


@pytest.mark.django_db
def test_falsches_passwort(client, inhaber):
    antwort = client.post(reverse("accounts:login"), {"email": inhaber.email, "passwort": "falsch"})
    assert antwort.status_code == 200
    assert "stimmen nicht" in antwort.content.decode()
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_abmelden_nur_per_post(client_inhaber):
    assert client_inhaber.get(reverse("accounts:logout")).status_code == 405
    client_inhaber.post(reverse("accounts:logout"))
    assert client_inhaber.get(reverse("web:start")).status_code == 302


@pytest.mark.django_db
def test_sitzung_ohne_zweiten_faktor_gilt_nicht_als_angemeldet(client, inhaber):
    client.force_login(inhaber)  # ohne zweiten Faktor
    antwort = client.get(reverse("web:start"))
    assert antwort.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_firma_wechseln_nur_zu_eigener_firma(client_inhaber, inhaber, firma, andere_firma):
    client_inhaber.post(reverse("accounts:firma_wechseln"), {"firma_id": andere_firma.pk})
    assert client_inhaber.session["firma_id"] == firma.pk
    Mitgliedschaft.objects.create(nutzer=inhaber, firma=andere_firma, rolle=Rolle.MITARBEITER)
    client_inhaber.post(reverse("accounts:firma_wechseln"), {"firma_id": andere_firma.pk})
    assert client_inhaber.session["firma_id"] == andere_firma.pk


@pytest.mark.django_db
def test_team_nur_fuer_inhaber(client_mitarbeiter, client_freigeber):
    assert client_mitarbeiter.get(reverse("accounts:team")).status_code == 403


@pytest.mark.django_db
def test_freigeber_darf_team_nicht_verwalten(client_freigeber):
    assert client_freigeber.get(reverse("accounts:team")).status_code == 403


@pytest.mark.django_db
def test_team_einladung_neues_konto(client_inhaber, firma, client):
    antwort = client_inhaber.post(reverse("accounts:team"), {"email": "Sabine@muster.example", "rolle": "freigeber"})
    assert antwort.status_code == 302
    assert len(mail.outbox) == 1
    link = next(z for z in mail.outbox[0].body.splitlines() if "/konto/einladung/" in z)
    pfad = link.split("http://localhost:8000")[1]
    client_inhaber.post(reverse("accounts:logout"))
    seite = client_inhaber.get(pfad)
    assert seite.status_code == 200
    daten = {"name": "Sabine", "passwort": PASSWORT, "passwort2": PASSWORT}
    for text in zustimmungspflichtig():
        daten[f"zustimmung_{text.slug}"] = "on"
    antwort = client_inhaber.post(pfad, daten)
    assert antwort.status_code == 302
    sabine = Nutzer.objects.get(email="sabine@muster.example")
    assert Mitgliedschaft.objects.get(nutzer=sabine).rolle == Rolle.FREIGEBER
    assert TeamEinladung.objects.get().angenommen_am is not None
    # Link ist danach verbraucht
    assert client.get(pfad).status_code == 404


@pytest.mark.django_db
def test_team_einladung_fuer_bestehendes_konto(client_inhaber, firma, fremder_inhaber, client):
    from tests.conftest import anmelden_als

    client_inhaber.post(reverse("accounts:team"), {"email": fremder_inhaber.email, "rolle": "mitarbeiter"})
    pfad = next(z for z in mail.outbox[0].body.splitlines() if "/konto/einladung/" in z).split("8000")[1]
    client_inhaber.post(reverse("accounts:logout"))
    assert client.get(pfad).status_code == 302  # erst anmelden
    anmelden_als(client, fremder_inhaber)
    assert client.post(pfad).status_code == 302
    assert Mitgliedschaft.objects.filter(nutzer=fremder_inhaber, firma=firma, rolle="mitarbeiter").exists()


@pytest.mark.django_db
def test_team_einladung_fremde_email_wird_abgelehnt(client_inhaber, firma, client, freigeber):
    from tests.conftest import anmelden_als

    client_inhaber.post(reverse("accounts:team"), {"email": "jemand@anders.example", "rolle": "mitarbeiter"})
    pfad = next(z for z in mail.outbox[0].body.splitlines() if "/konto/einladung/" in z).split("8000")[1]
    anmelden_als(client, freigeber)
    client.post(pfad)
    assert TeamEinladung.objects.get().angenommen_am is None


@pytest.mark.django_db
def test_passwort_vergessen_sendet_mail(client, inhaber):
    antwort = client.post(reverse("accounts:passwort_vergessen"), {"email": inhaber.email})
    assert antwort.status_code == 302
    assert len(mail.outbox) == 1
    assert "/konto/passwort/neu/" in mail.outbox[0].body
