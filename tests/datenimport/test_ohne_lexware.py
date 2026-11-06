"""M9-08: Excel-Import ohne Lexware. Kunden und offene Rechnungen nur in Belegfluss, Artikel nur mit Lexware."""

from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from audit.models import Protokolleintrag
from connectors.models import Verbindung
from connectors.services import ohne_lexware
from datenimport import services
from datenimport.models import ImportVorgang
from datenimport.services import ImportNichtMoeglich
from ledger.models import Beleg, Kontakt
from tests.datenimport.test_ablauf import KUNDEN_CSV, _vorgang

pytestmark = pytest.mark.django_db

POSTEN_CSV = (
    "Rechnungsnr;Datum;Fällig am;Kunde;E-Mail;Betrag;Bezahlt\n"
    "2026-201;01.09.2026;15.09.2026;Gasthof Linde;wirt@linde.example;1.190,00;\n"
    "2026-202;01.10.2026;15.10.2026;gasthof  linde;;595,00;95,00\n"  # gleicher neuer Kunde
    "2026-203;01.10.2026;31.10.2026;Huber Hausverwaltung GmbH;;300,00;\n"  # Kunde aus Rechnungskopie
    "2026-204;01.10.2026;31.10.2026;;;300,00;\n"  # Fehler: Kunde fehlt
).encode()


def test_ohne_lexware_heisst_nie_verbunden_oder_getrennt(firma, verbindung):
    assert not ohne_lexware(firma)
    verbindung.status = Verbindung.Status.FEHLER
    verbindung.save()
    assert not ohne_lexware(firma)  # gestörte Verbindung: nicht still auf „ohne Lexware“ umschalten
    verbindung.status = Verbindung.Status.GETRENNT
    verbindung.save()
    assert ohne_lexware(firma)


def test_kunden_nur_in_belegfluss(firma, inhaber, lexware_api):
    Kontakt.objects.create(firma=firma, extern_id="lokal-1", name="Bau AG", email="rechnung@bau-ag.example")
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    assert {z["nr"]: z["grund"] for z in vorgang.vorschau}[2] == "Schon in Belegfluss vorhanden"
    vorgang.kundentyp_uebernehmen = True
    vorgang.save()
    services.freigeben(vorgang, inhaber)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG and vorgang.ergebnis["angelegt"] == 2
    dach = Kontakt.objects.get(firma=firma, name="Dach & Co KG")
    assert dach.extern_id.startswith("lokal-") and dach.excel_nummer == "K-2" and dach.email == "info@dach.example"
    assert dach.adresse == "Dach & Co KG\nPaul Polier\nRing 3\n20095 Hamburg" and dach.ist_unternehmen_extern
    assert dach.kundentyp == "unternehmer"  # „Firma“ zählt wie im Lexware-Weg als Unternehmer (bestätigt)
    erika = Kontakt.objects.get(firma=firma, name="Erika Musterfrau")
    assert erika.kundentyp == "privat" and erika.ist_unternehmen_extern is False  # ausdrücklich bestätigt
    assert lexware_api.calls.call_count == 0
    assert Protokolleintrag.objects.filter(ereignis="kontakt.aus_import_angelegt").count() == 2
    assert Protokolleintrag.objects.filter(ereignis="import.fertig").count() == 1


def test_kundentyp_ohne_bestaetigung_nicht_uebernommen(firma, inhaber):
    services.freigeben(_vorgang(firma, inhaber, "kunden", KUNDEN_CSV), inhaber)
    assert set(Kontakt.objects.fuer(firma).values_list("kundentyp", flat=True)) == {"unbekannt"}


def test_artikel_nur_mit_lexware(firma, inhaber, client_inhaber):
    vorgang = _vorgang(
        firma, inhaber, "artikel", b"Bezeichnung;Einheit;Preis;MwSt;Art\nStunde;h;58,00;19;Dienstleistung\n"
    )
    with pytest.raises(ImportNichtMoeglich, match="nur mit Lexware"):
        services.freigeben(vorgang, inhaber)
    antwort = client_inhaber.post(
        reverse("datenimport:uebersicht"),
        {"art": "artikel", "datei": SimpleUploadedFile("a.csv", b"Bezeichnung;Einheit\nX;h\n")},
    )
    assert "nur mit Lexware importieren" in antwort.content.decode()


def test_offene_rechnungen_legen_fehlende_kunden_an(firma, inhaber, lexware_api):
    from quellen import kopien
    from tests.quellen.hilfen import datei

    huber = kopien.einlesen(firma, "re.xml", datei("xrechnung_cii.xml")).beleg.kontakt  # Kunde aus Rechnungskopie
    vorgang = _vorgang(firma, inhaber, "posten", POSTEN_CSV)
    zeilen = {z["nr"]: z for z in vorgang.vorschau}
    assert zeilen[2]["status"] == "neu" and "wird in Belegfluss neu angelegt" in zeilen[2]["grund"]
    assert zeilen[3]["status"] == "neu" and zeilen[3]["grund"] == "Neuer Kunde „gasthof  linde“ wie in Zeile 2."
    assert zeilen[4]["status"] == "neu" and zeilen[4]["daten"]["kontakt_id"] == huber.pk
    assert zeilen[5]["status"] == "fehler"
    services.freigeben(vorgang, inhaber)
    vorgang.refresh_from_db()
    assert vorgang.ergebnis["angelegt"] == 3
    linde = Kontakt.objects.get(firma=firma, name="Gasthof Linde")
    assert linde.email == "wirt@linde.example" and linde.kundentyp == "unbekannt"
    assert Kontakt.objects.filter(firma=firma, name__iexact="gasthof linde").count() == 1
    assert set(Beleg.objects.filter(kontakt=linde).values_list("nummer", "offen")) == {
        ("2026-201", Decimal("1190.00")),
        ("2026-202", Decimal("500.00")),
    }
    assert Beleg.objects.get(nummer="2026-203").kontakt == huber
    assert lexware_api.calls.call_count == 0


def test_mit_lexware_bleibt_der_kunde_pflicht(firma, inhaber, verbindung):
    vorgang = _vorgang(firma, inhaber, "posten", POSTEN_CSV)
    assert {z["status"] for z in vorgang.vorschau} == {"fehler"}
    assert "nicht in Lexware" in vorgang.vorschau[0]["grund"]


def test_oberflaeche_ohne_lexware(client_inhaber, firma, inhaber):
    seite = client_inhaber.get(reverse("datenimport:uebersicht")).content.decode()
    assert "Sie arbeiten ohne Lexware" in seite and "Lexware ist nicht verbunden" not in seite
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    seite = client_inhaber.get(reverse("datenimport:vorgang", args=[vorgang.pk])).content.decode()
    assert "Kunden in Belegfluss anlegen" in seite and "nur in Belegfluss angelegt" in seite
    antwort = client_inhaber.post(reverse("datenimport:freigeben", args=[vorgang.pk]), follow=True)
    assert "3 Kunden sind jetzt in Belegfluss." in antwort.content.decode()


def test_einrichtung_erkennt_den_weg_ohne_lexware(client_inhaber, firma, inhaber):
    seite = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "aus Excel übernehmen" in seite and "1. Lexware verbinden" in seite
    services.freigeben(_vorgang(firma, inhaber, "posten", POSTEN_CSV), inhaber)
    seite = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "1. Rechnungen anbinden" in seite
    start = client_inhaber.get(reverse("web:start")).content.decode()
    assert "Noch keine Verbindung zu Lexware" not in start
