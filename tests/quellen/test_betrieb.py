"""M9-07 (K9, K10): Löschfristen, Trennen von Lexware, Firma löschen, Navigation und Einrichtung ohne Lexware."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.loeschfristen import ausfuehren, firma_loeschen
from audit.models import Protokolleintrag
from connectors.models import Verbindung
from ledger.models import Beleg, Kontakt
from quellen import kopien, zahlungen
from quellen.models import Kontoauszug, Kopieadresse, Rechnungskopie, Zahlung
from tests.quellen.hilfen import datei, text_pdf

pytestmark = pytest.mark.django_db


def _daten(firma, inhaber):
    kopie = kopien.einlesen(firma, "re.xml", datei("xrechnung_cii.xml"))
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    return kopie


def test_nach_12_monaten_geloescht(firma, inhaber, andere_firma):
    _daten(firma, inhaber)
    _daten(andere_firma, None)
    Rechnungskopie.objects.filter(firma=firma).update(loeschen_ab=timezone.now() - timedelta(minutes=1))
    Zahlung.objects.filter(firma=firma).update(loeschen_ab=timezone.now() - timedelta(minutes=1))
    Kontoauszug.objects.filter(firma=firma).update(loeschen_ab=timezone.now() - timedelta(minutes=1))
    ausfuehren()
    for modell in (Rechnungskopie, Zahlung, Kontoauszug):
        assert not modell.objects.fuer(firma).exists(), modell
        assert modell.objects.fuer(andere_firma).exists(), modell
    assert Beleg.objects.fuer(firma).filter(quelle="kopie").exists()  # der Posten selbst bleibt
    eintrag = Protokolleintrag.objects.filter(firma=firma, ereignis="loeschfristen.ausgefuehrt").latest("zeit")
    assert eintrag.daten["zahlungen"] == 3 and eintrag.daten["rechnungskopien"] == 1


def test_pdf_text_spaetestens_nach_7_tagen(firma):
    kopie = kopien.einlesen(firma, "scan.pdf", text_pdf("Rechnung 2026-117", "Bau AG"))
    assert kopie.text
    ausfuehren()
    kopie.refresh_from_db()
    assert kopie.text  # KI hat noch nicht gelesen, Frist läuft
    ausfuehren(timezone.now() + timedelta(days=7, minutes=1))
    kopie.refresh_from_db()
    assert kopie.text == "" and kopie.status == "pruefung"


def test_trennen_von_lexware_laesst_posten_aus_kopien(firma, inhaber, verbindung):
    lexware_kunde = Kontakt.objects.create(
        firma=firma, extern_id="lx-1", name="Huber", email="rechnung@huber-hv.example"
    )
    Beleg.objects.create(firma=firma, extern_id="inv-1", nummer="LX-1", kontakt=lexware_kunde, offen=Decimal("5"))
    Kontakt.objects.create(firma=firma, extern_id="lx-2", name="Nur Lexware")
    kopie = kopien.einlesen(firma, "re.xml", datei("xrechnung_cii.xml"))
    assert kopie.beleg.kontakt == lexware_kunde  # über die E-Mail gefunden
    Verbindung.objects.filter(pk=verbindung.pk).update(
        status=Verbindung.Status.GETRENNT, getrennt_am=timezone.now() - timedelta(days=31)
    )
    ausfuehren()
    assert list(Beleg.objects.fuer(firma).values_list("nummer", flat=True)) == ["RE-2026-0412"]
    assert list(Kontakt.objects.fuer(firma).values_list("extern_id", flat=True)) == ["lx-1"]


def test_firma_loeschen_loescht_auch_kopien_und_zahlungen(firma, inhaber):
    _daten(firma, inhaber)
    Kopieadresse.objects.create(firma=firma)
    anzahlen = firma_loeschen(firma)
    assert anzahlen["zahlungen"] == 3 and anzahlen["rechnungskopien"] == 1 and anzahlen["kopieadresse"] == 1
    for modell in (Rechnungskopie, Zahlung, Kontoauszug, Kopieadresse, Beleg, Kontakt):
        assert not modell.objects.fuer(firma).exists(), modell


def test_navigation_mit_zaehler(client_inhaber, firma, inhaber):
    _daten(firma, inhaber)
    kopien.einlesen(firma, "fremd.xml", datei("xrechnung_cii.xml").replace(b"EUR", b"CHF"))  # in die Prüfung
    offen = Rechnungskopie.objects.filter(status="pruefung").count() + Zahlung.objects.filter(status="neu").count()
    assert offen == 4
    seite = client_inhaber.get(reverse("web:start")).content.decode()
    assert reverse("quellen:uebersicht") in seite and "Abgleich" in seite and f">{offen}<" in seite


def test_navigation_nicht_fuer_mitarbeiter(client_mitarbeiter):
    seite = client_mitarbeiter.get(reverse("web:start")).content.decode()
    assert reverse("quellen:uebersicht") not in seite


def test_einrichtung_ohne_lexware(client_inhaber, firma):
    seite = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "Lexware verbinden" in seite and "Kein Lexware?" in seite
    Kopieadresse.objects.create(firma=firma)
    seite = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "1. Rechnungen anbinden" in seite and "Kein Lexware?" not in seite
    assert "Einrichtung" in client_inhaber.get(reverse("web:einstellungen")).content.decode()
    assert "Ohne Lexware: Rechnungskopien" in client_inhaber.get(reverse("web:einstellungen")).content.decode()
