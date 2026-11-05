"""M8-04/05: Testanruf im Browser (J6) und Anmeldung eines Anrufs durch Asterisk (J7)."""

import json

import pytest
from django.urls import reverse

from telefon.models import Gespraech, Rueckruf, Telefonassistent
from tests.ki_fake import antwort

pytestmark = pytest.mark.django_db


def _ki_antwort(text, beenden=False, **erfasst):
    felder = {"name": "", "anliegen": "", "rueckrufnummer": "", "beste_zeit": "", "dringlichkeit": ""}
    felder.update(erfasst)
    return antwort({"antwort": text, "erfasst": felder, "beenden": beenden})


def test_testanruf_per_text(client_mitarbeiter, firma, ki):
    ki(
        _ki_antwort(
            "Danke, ich notiere: Heizung fällt aus.", beenden=True, name="Herr Test", anliegen="Heizung fällt aus"
        )
    )
    assert "Testanruf im Browser" in client_mitarbeiter.get(reverse("telefon:testanruf")).content.decode()
    start = client_mitarbeiter.post(reverse("telefon:test_start"), {"nummer": "0151 111"}).json()
    assert "digitaler Assistent" in start["antwort"]
    g = Gespraech.objects.get(uuid=start["gespraech"])
    assert g.kanal == "test" and g.anrufer_nummer == "0151111"
    daten = client_mitarbeiter.post(
        reverse("telefon:test_nachricht", args=[start["gespraech"]]), {"text": "Hallo, meine Heizung fällt aus."}
    ).json()
    assert daten["beendet"] and daten["rueckruf"] and "gehoert" not in daten
    r = Rueckruf.objects.get(gespraech=g)
    assert r.test and r.name == "Herr Test"


def test_testanruf_per_sprache(client_inhaber, firma, ki, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile

    import capture.transkription

    monkeypatch.setattr(
        capture.transkription, "transkribieren", lambda audio, name, mime: "Hier spricht Erika, Fenster klemmt."
    )
    ki(_ki_antwort("Danke. Passt die Nummer, von der Sie anrufen?", anliegen="Fenster klemmt"))
    start = client_inhaber.post(reverse("telefon:test_start")).json()
    daten = client_inhaber.post(
        reverse("telefon:test_nachricht", args=[start["gespraech"]]),
        {"audio": SimpleUploadedFile("beitrag.webm", b"\x1a\x45\xdf\xa3audio", content_type="audio/webm")},
    ).json()
    assert daten["gehoert"] == "Hier spricht Erika, Fenster klemmt." and not daten["beendet"]
    ende = client_inhaber.post(reverse("telefon:test_ende", args=[start["gespraech"]])).json()
    assert ende["beendet"] and ende["rueckruf"]


def test_testanruf_fremde_firma_404(client_inhaber, andere_firma):
    from telefon import gespraech as fuehrung

    g, _ = fuehrung.starten(andere_firma, Gespraech.Kanal.TEST)
    assert client_inhaber.post(reverse("telefon:test_nachricht", args=[str(g.uuid)]), {"text": "x"}).status_code == 404
    assert client_inhaber.post(reverse("telefon:test_nachricht", args=["kein-uuid"]), {"text": "x"}).status_code == 404


def test_asterisk_anmeldung(client, firma, settings):
    settings.TELEFON_ASTERISK_TOKEN = "geheim-123"
    url = reverse("telefon:asterisk_anruf")
    assert client.post(url, {"did": "+4930111", "clip": "0151", "token": "falsch"}).status_code == 403
    settings.TELEFON_ASTERISK_TOKEN = ""
    assert client.post(url, {"did": "+4930111", "token": ""}).status_code == 403  # ohne Geheimnis nie offen
    settings.TELEFON_ASTERISK_TOKEN = "geheim-123"
    assert client.post(url, {"did": "+4930111", "token": "geheim-123"}).status_code == 404  # unbekannte Nummer
    Telefonassistent.objects.create(firma=firma, rufnummer="+4930111", aktiv=False)
    assert client.post(url, {"did": "+49 30 111", "token": "geheim-123"}).status_code == 404  # ausgeschaltet
    Telefonassistent.objects.filter(firma=firma).update(aktiv=True)
    antwort = client.post(url, {"did": "+49 30 111", "clip": "0151 222", "token": "geheim-123"})
    assert antwort.status_code == 200
    g = Gespraech.objects.get(uuid=antwort.content.decode())
    assert (g.firma, g.kanal, g.anrufer_nummer, g.angerufene_nummer) == (firma, "telefon", "0151222", "+4930111")
    assert json.dumps(g.verlauf[0]["text"])  # Ansage steht im Verlauf
