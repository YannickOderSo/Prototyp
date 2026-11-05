"""M6-08: Oberfläche des Imports (Rollen, Upload, Zuordnung, Vorschau, Freigabe, Zahlung, Vorlagen)."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from datenimport.models import ImportVorgang
from ledger.models import Beleg, Kontakt

pytestmark = pytest.mark.django_db

POSTEN = "Rechnungsnr;Datum;Fällig;Kunde;Betrag\n2024-117;01.09.2026;15.09.2026;Bau AG;1.190,00\n".encode()


def _datei(inhalt, name="offen.csv"):
    datei = io.BytesIO(inhalt)
    datei.name = name
    return datei


@pytest.fixture
def bau(firma):
    return Kontakt.objects.create(firma=firma, extern_id="kon-bau", name="Bau AG", kundentyp="unternehmer")


def test_mitarbeiter_darf_nicht_importieren(client_mitarbeiter):
    assert client_mitarbeiter.get(reverse("datenimport:uebersicht")).status_code == 403
    antwort = client_mitarbeiter.post(reverse("datenimport:uebersicht"), {"art": "posten", "datei": _datei(POSTEN)})
    assert antwort.status_code == 403
    assert not ImportVorgang.objects.exists()


def test_vorlagen_herunterladen(client_mitarbeiter):
    antwort = client_mitarbeiter.get(reverse("datenimport:vorlage", args=["kunden", "csv"]))
    assert antwort.status_code == 200 and b"Firma" in antwort.content
    antwort = client_mitarbeiter.get(reverse("datenimport:vorlage", args=["artikel", "xlsx"]))
    assert antwort.content.startswith(b"PK")
    assert client_mitarbeiter.get(reverse("datenimport:vorlage", args=["geheim", "csv"])).status_code == 404


def test_ganzer_ablauf_offene_rechnungen(client_freigeber, firma, freigeber, bau):
    antwort = client_freigeber.post(reverse("datenimport:uebersicht"), {"art": "posten", "datei": _datei(POSTEN)})
    vorgang = ImportVorgang.objects.get(firma=firma)
    assert antwort.url == reverse("datenimport:vorgang", args=[vorgang.pk])
    seite = client_freigeber.get(antwort.url).content.decode()
    assert "Spalten zuordnen" in seite and "Rechnungsnr" in seite
    # Vorschlag übernehmen (Zuordnung aus den Überschriften)
    daten = {f"feld_{k}": str(v) for k, v in vorgang.zuordnung.items()}
    client_freigeber.post(reverse("datenimport:zuordnung", args=[vorgang.pk]), daten)
    vorgang.refresh_from_db()
    assert vorgang.status == "vorschau"
    seite = client_freigeber.get(reverse("datenimport:vorgang", args=[vorgang.pk])).content.decode()
    assert "1 offene Rechnungen in Belegfluss übernehmen" in seite and "2024-117 · Bau AG" in seite
    client_freigeber.post(reverse("datenimport:freigeben", args=[vorgang.pk]))
    vorgang.refresh_from_db()
    assert vorgang.status == "fertig" and vorgang.freigegeben_von == freigeber
    beleg = Beleg.objects.get(firma=firma, nummer="2024-117")
    seite = client_freigeber.get(reverse("ledger:beleg", args=[beleg.pk])).content.decode()
    assert "Aus Excel übernommen" in seite and "Zahlung eintragen" in seite
    antwort = client_freigeber.post(reverse("datenimport:zahlung", args=[beleg.pk]), {"offen": "190,00"})
    beleg.refresh_from_db()
    assert beleg.offen == Decimal("190.00")
    client_freigeber.post(reverse("datenimport:zahlung", args=[beleg.pk]), {"bezahlt_am": "2026-11-04"})
    beleg.refresh_from_db()
    assert beleg.status == "bezahlt" and beleg.bezahlt_am == date(2026, 11, 4)


def test_zuordnung_fehlt_und_doppelte_spalte(client_inhaber, firma, inhaber, bau):
    client_inhaber.post(reverse("datenimport:uebersicht"), {"art": "posten", "datei": _datei(POSTEN)})
    vorgang = ImportVorgang.objects.get(firma=firma)
    antwort = client_inhaber.post(
        reverse("datenimport:zuordnung", args=[vorgang.pk]), {"feld_rechnungsnummer": "0"}, follow=True
    )
    assert "Bitte noch zuordnen" in antwort.content.decode()
    antwort = client_inhaber.post(
        reverse("datenimport:zuordnung", args=[vorgang.pk]),
        {"feld_rechnungsnummer": "0", "feld_kunde": "0"},
        follow=True,
    )
    assert "nur einem Feld" in antwort.content.decode()
    vorgang.refresh_from_db()
    assert vorgang.status == "zuordnung"


def test_kaputte_datei_zeigt_fehler(client_inhaber):
    antwort = client_inhaber.post(
        reverse("datenimport:uebersicht"), {"art": "kunden", "datei": _datei(b"\x00\x01\x02binaer", "k.xlsx")}
    )
    assert antwort.status_code == 200
    assert not ImportVorgang.objects.exists()
    assert "errorlist" in antwort.content.decode()


def test_zahlung_fuer_lexware_beleg_abgelehnt(client_inhaber, firma, bau):
    beleg = Beleg.objects.create(
        firma=firma, extern_id="inv-1", nummer="RE1", kontakt=bau, offen=Decimal("10"), brutto=Decimal("10")
    )
    seite = client_inhaber.get(reverse("ledger:beleg", args=[beleg.pk])).content.decode()
    assert "Zahlung eintragen" not in seite
    antwort = client_inhaber.post(
        reverse("datenimport:zahlung", args=[beleg.pk]), {"bezahlt_am": "2026-11-04"}, follow=True
    )
    assert "aus Lexware" in antwort.content.decode()
    beleg.refresh_from_db()
    assert beleg.offen == Decimal("10")


def test_verwerfen(client_inhaber, firma, bau):
    client_inhaber.post(reverse("datenimport:uebersicht"), {"art": "posten", "datei": _datei(POSTEN)})
    vorgang = ImportVorgang.objects.get(firma=firma)
    antwort = client_inhaber.post(reverse("datenimport:verwerfen", args=[vorgang.pk]))
    assert antwort.url == reverse("datenimport:uebersicht")
    vorgang.refresh_from_db()
    assert vorgang.status == "verworfen"


def test_hinweise_in_einstellungen_und_einrichtung(client_inhaber, verbindung):
    assert reverse("datenimport:uebersicht") in client_inhaber.get(reverse("web:einstellungen")).content.decode()
    from django.utils import timezone

    from connectors.models import Verbindung

    Verbindung.objects.filter(pk=verbindung.pk).update(erstimport_fertig=timezone.now())
    seite = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "Bisher mit Excel gearbeitet?" in seite
