"""M3-03: Transkript wird angezeigt und ist editierbar, bevor der Entwurf entsteht (E3)."""

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.models import Erfassung
from jobs.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def erfassung(firma, mitarbeiter):
    return Erfassung.objects.create(
        firma=firma,
        erstellt_von=mitarbeiter,
        kanal="aufnahme",
        status="transkribiert",
        transkript="Rechnung für Bau AG, fuffzehn Meter Sockelleiste",
    )


def test_transkript_wird_angezeigt(client_mitarbeiter, erfassung):
    html = client_mitarbeiter.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "Transkript prüfen" in html
    assert "fuffzehn Meter Sockelleiste" in html
    assert "Entwurf erzeugen" in html


def test_bearbeiten_und_speichern(client_mitarbeiter, erfassung, mitarbeiter):
    client_mitarbeiter.post(
        reverse("capture:transkript", args=[erfassung.pk]),
        {"transkript": "Rechnung für Bau AG, 15 Meter Sockelleiste", "aktion": "speichern"},
    )
    erfassung.refresh_from_db()
    assert erfassung.transkript == "Rechnung für Bau AG, 15 Meter Sockelleiste"
    assert erfassung.transkript_bearbeitet
    assert erfassung.status == "transkribiert"
    assert not Job.objects.filter(typ="capture.extrahieren").exists()
    assert Protokolleintrag.objects.get(ereignis="erfassung.transkript_bearbeitet").nutzer == mitarbeiter


def test_erzeugen_plant_extraktion(client_mitarbeiter, erfassung):
    client_mitarbeiter.post(
        reverse("capture:transkript", args=[erfassung.pk]), {"transkript": "Rechnung Bau AG 15 m", "aktion": "erzeugen"}
    )
    erfassung.refresh_from_db()
    assert erfassung.status == "extrahiert"
    assert Job.objects.filter(typ="capture.extrahieren", payload__erfassung_id=erfassung.pk).exists()


def test_aus_pruefung_neu_erzeugen(client_inhaber, erfassung):
    erfassung.status = "pruefung"
    erfassung.save()
    html = client_inhaber.get(reverse("capture:detail", args=[erfassung.pk])).content.decode()
    assert "Entwurf neu erzeugen" in html
    client_inhaber.post(reverse("capture:transkript", args=[erfassung.pk]), {"transkript": "neu", "aktion": "erzeugen"})
    erfassung.refresh_from_db()
    assert erfassung.status == "extrahiert"


@pytest.mark.parametrize("status", ["freigegeben", "uebertragen", "verworfen", "wartet"])
def test_nach_freigabe_nicht_mehr_bearbeitbar(client_inhaber, erfassung, status):
    erfassung.status = status
    erfassung.save()
    antwort = client_inhaber.post(
        reverse("capture:transkript", args=[erfassung.pk]),
        {"transkript": "geändert", "aktion": "erzeugen"},
        follow=True,
    )
    assert "nicht mehr bearbeitet" in antwort.content.decode()
    erfassung.refresh_from_db()
    assert erfassung.transkript != "geändert"


def test_leer_kann_nicht_erzeugt_werden(client_inhaber, firma):
    leer = Erfassung.objects.create(firma=firma, kanal="aufnahme", status="transkribiert")
    antwort = client_inhaber.post(
        reverse("capture:transkript", args=[leer.pk]), {"transkript": "", "aktion": "erzeugen"}, follow=True
    )
    assert "keinen Text" in antwort.content.decode()
