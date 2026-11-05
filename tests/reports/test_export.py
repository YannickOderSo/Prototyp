"""M4-02: Export je Firma (F3) mit CSV-Injection-Schutz."""

import csv
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.urls import reverse

from audit.models import Protokolleintrag
from audit.services import protokolliere
from dunning.models import Mahnvorschlag, Versand
from ledger.models import Beleg, Kontakt
from reports.export import csv_text, zelle, zip_export

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("wert", "erwartet"),
    [
        ('=HYPERLINK("http://x")', '\'=HYPERLINK("http://x")'),
        ("+49 170", "'+49 170"),
        ("-1+2", "'-1+2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tTab", "'\tTab"),
        ("Bau AG", "Bau AG"),
        (None, ""),
        (Decimal("12.50"), "12.50"),
        ({"a": "=1"}, '{"a": "=1"}'),
    ],
)
def test_zelle_schuetzt_vor_formeln(wert, erwartet):
    assert zelle(wert) == erwartet


def test_csv_format():
    text = csv_text(["a", "b"], [["=1", "x;y"]])
    assert text.startswith("﻿a;b\r\n")
    assert '\'=1;"x;y"' in text


@pytest.fixture
def daten(firma, andere_firma, inhaber):
    k = Kontakt.objects.create(firma=firma, extern_id="k", name="=Böse GmbH", kundentyp="unternehmer")
    b = Beleg.objects.create(
        firma=firma, extern_id="b", nummer="RE1", kontakt=k, kontakt_name="=Böse GmbH", offen=Decimal("10")
    )
    v = Mahnvorschlag.objects.create(firma=firma, beleg=b, stufe=0, status="versendet", gesamt=Decimal("10.00"))
    Versand.objects.create(firma=firma, vorschlag=v, empfaenger="a@b.example", betreff="+Erinnerung", text="x")
    protokolliere(firma, "mahnung.freigegeben", nutzer=inhaber, objekt=v)
    fremd = Beleg.objects.create(firma=andere_firma, extern_id="f", nummer="FREMD-1", offen=1)
    Mahnvorschlag.objects.create(firma=andere_firma, beleg=fremd, stufe=0)
    protokolliere(andere_firma, "fremd.ereignis")
    return firma


def _dateien(inhalt):
    archiv = zipfile.ZipFile(io.BytesIO(inhalt))
    return {name: archiv.read(name).decode("utf-8-sig") for name in archiv.namelist()}


def test_zip_enthaelt_alles_nur_von_der_eigenen_firma(daten):
    dateien = _dateien(zip_export(daten))
    assert set(dateien) == {
        "vorschlaege.csv",
        "versaende.csv",
        "angebotserinnerungen.csv",
        "protokoll.csv",
        "erfassungen.csv",
        "LIESMICH.txt",
    }
    vorschlaege = list(csv.DictReader(io.StringIO(dateien["vorschlaege.csv"]), delimiter=";"))
    assert len(vorschlaege) == 1
    assert vorschlaege[0]["kunde"] == "'=Böse GmbH"
    assert "FREMD" not in "".join(dateien.values())
    assert "fremd.ereignis" not in dateien["protokoll.csv"]
    assert "'+Erinnerung" in dateien["versaende.csv"]
    assert "mahnung.freigegeben" in dateien["protokoll.csv"]


def test_inhaber_kann_jederzeit_exportieren(client_inhaber, daten):
    antwort = client_inhaber.get(reverse("reports:export"))
    assert antwort["Content-Type"] == "application/zip"
    assert 'attachment; filename="cockpit-export-' in antwort["Content-Disposition"]
    assert "vorschlaege.csv" in _dateien(antwort.content)
    assert Protokolleintrag.objects.filter(ereignis="export.erstellt").exists()


def test_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("reports:export")).status_code == 403


def test_kommando(daten, tmp_path):
    ziel = tmp_path / "export.zip"
    call_command("firma_export", daten.pk, str(ziel))
    assert "protokoll.csv" in _dateien(ziel.read_bytes())
