"""M3-01: Upload und Browser-Aufnahme (E1), Dateilimits, Typprüfung nach Inhalt, Ablage außerhalb des Webroots."""

from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from audit.models import Protokolleintrag
from capture.dateien import DateiAbgelehnt, lesen, loeschen, typ_erkennen
from capture.models import Datei, Erfassung
from jobs.models import Job

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture"
pytestmark = pytest.mark.django_db


def _datei(name, inhalt, typ="application/octet-stream"):
    return SimpleUploadedFile(name, inhalt, content_type=typ)


@pytest.mark.parametrize(
    ("inhalt", "name", "art"),
    [
        (b"\x1a\x45\xdf\xa3....", "a.webm", "audio"),
        (b"OggS....", "a.ogg", "audio"),
        (b"\x00\x00\x00\x20ftypM4A \x00", "a.m4a", "audio"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "a.wav", "audio"),
        (b"ID3\x04...", "a.mp3", "audio"),
        (b"\xff\xd8\xff\xe0JFIF", "f.jpg", "bild"),
        (b"\x89PNG\r\n\x1a\n....", "f.png", "bild"),
        (b"\x00\x00\x00\x18ftypheic", "f.heic", "bild"),
        (b"%PDF-1.7\n", "x.pdf", "pdf"),
        (b"Datum;Kunde\n2026-11-02;Bau AG\n", "z.csv", "csv"),
        (b"From: a@b.example\nSubject: Auftrag\n\nHallo", "m.eml", "mail"),
        ("Notiz für Müller".encode("cp1252"), "n.txt", "text"),
    ],
)
def test_typ_nach_inhalt(inhalt, name, art):
    assert typ_erkennen(inhalt, name).art == art


@pytest.mark.parametrize(
    ("inhalt", "name"),
    [
        (b"MZ\x90\x00", "rechnung.pdf"),  # Programm mit PDF-Endung
        (b"PK\x03\x04", "x.zip"),
        (b"\x00\x01\x02\x03\x00", "unbekannt.bin"),
        (b"<html><script>alert(1)</script>", "x.txt"),
    ],
)
def test_gefaehrliches_oder_unbekanntes_wird_abgelehnt(inhalt, name):
    with pytest.raises(DateiAbgelehnt):
        typ_erkennen(inhalt, name)


def test_upload_legt_erfassung_an_und_plant_aufbereitung(client_mitarbeiter, firma, mitarbeiter):
    antwort = client_mitarbeiter.post(
        reverse("capture:hochladen"),
        {
            "dateien": [
                _datei("stundenzettel.jpg", (FIX / "stundenzettel.jpg").read_bytes()),
                _datei("zeiten.csv", (FIX / "zeiten.csv").read_bytes()),
            ],
            "notiz": "Abrechnung November",
        },
    )
    erfassung = Erfassung.objects.get()
    assert antwort["Location"] == reverse("capture:detail", args=[erfassung.pk])
    assert erfassung.firma == firma
    assert erfassung.erstellt_von == mitarbeiter
    assert erfassung.kanal == "upload"
    assert erfassung.notiz == "Abrechnung November"
    assert sorted(d.art for d in Datei.objects.filter(erfassung=erfassung)) == ["bild", "csv"]
    assert Job.objects.filter(typ="capture.aufbereiten", payload__erfassung_id=erfassung.pk).exists()
    assert Protokolleintrag.objects.filter(ereignis="erfassung.angelegt").exists()


def test_aufnahme_per_fetch(client_inhaber):
    antwort = client_inhaber.post(
        reverse("capture:hochladen"),
        {"aufnahme": _datei("aufnahme.webm", (FIX / "memo.webm").read_bytes(), "audio/webm")},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert antwort.status_code == 200
    erfassung = Erfassung.objects.get()
    assert antwort.json() == {"weiter": reverse("capture:detail", args=[erfassung.pk])}
    assert erfassung.kanal == "aufnahme"
    assert Datei.objects.get().art == "audio"


def test_dateien_liegen_ausserhalb_des_webroots(client_inhaber):
    client_inhaber.post(reverse("capture:hochladen"), {"dateien": [_datei("z.csv", (FIX / "zeiten.csv").read_bytes())]})
    datei = Datei.objects.get()
    pfad = Path(settings.DATEIABLAGE) / datei.pfad
    assert pfad.exists()
    assert oct(pfad.stat().st_mode)[-3:] == "600"
    assert not str(pfad.resolve()).startswith(str(Path(settings.STATIC_ROOT).resolve()))
    assert "static" not in pfad.parts
    assert ".." not in datei.pfad and datei.pfad.startswith(f"{datei.firma_id}/")
    assert lesen(datei) == (FIX / "zeiten.csv").read_bytes()
    assert datei.sha256 and datei.groesse > 0
    loeschen(datei)
    assert not pfad.exists()
    datei.refresh_from_db()
    assert datei.geloescht_am is not None
    with pytest.raises(FileNotFoundError):
        lesen(datei)


def test_zu_grosse_datei_wird_abgelehnt(client_inhaber, monkeypatch):
    import capture.dateien

    monkeypatch.setattr(capture.dateien, "MAX_DATEI_BYTES", 100)
    antwort = client_inhaber.post(
        reverse("capture:hochladen"), {"dateien": [_datei("gross.jpg", b"\xff\xd8\xff" + b"0" * 200)]}, follow=True
    )
    assert "größer als 25 MB" in antwort.content.decode()
    assert not Erfassung.objects.exists()


def test_mehr_als_zehn_dateien(client_inhaber):
    dateien = [_datei(f"n{i}.txt", b"Notiz") for i in range(11)]
    antwort = client_inhaber.post(reverse("capture:hochladen"), {"dateien": dateien}, follow=True)
    assert antwort.status_code in (200, 400)
    assert not Erfassung.objects.exists()


def test_falscher_typ_nichts_gespeichert(client_inhaber):
    antwort = client_inhaber.post(
        reverse("capture:hochladen"),
        {"dateien": [_datei("ok.csv", b"a;b\n1;2\n"), _datei("boese.pdf", b"MZ\x90\x00bin")]},
        HTTP_X_REQUESTED_WITH="fetch",
    )
    assert antwort.status_code == 400
    assert "Programme" in antwort.json()["fehler"]
    assert not Erfassung.objects.exists()
    assert not Datei.objects.exists()


def test_leere_erfassung(client_inhaber):
    antwort = client_inhaber.post(reverse("capture:hochladen"), {"notiz": "  "}, follow=True)
    assert "Bitte nehmen Sie etwas auf" in antwort.content.decode()


def test_nur_notiz_reicht(client_inhaber):
    client_inhaber.post(reverse("capture:hochladen"), {"notiz": "Angebot Wohnzimmer streichen"})
    assert Erfassung.objects.get().notiz == "Angebot Wohnzimmer streichen"


def test_seiten_und_aufnahme_skript(client_mitarbeiter):
    html = client_mitarbeiter.get(reverse("capture:neu")).content.decode()
    assert "Keine Kundengespräche aufnehmen" in html
    assert 'data-max-sekunden="300"' in html
    assert "/static/capture/aufnahme.js" in html
    assert client_mitarbeiter.get(reverse("capture:liste")).status_code == 200


def test_ohne_anmeldung_kein_upload(client):
    antwort = client.post(reverse("capture:hochladen"), {"notiz": "x"})
    assert antwort.status_code == 302
    assert not Erfassung.objects.exists()
