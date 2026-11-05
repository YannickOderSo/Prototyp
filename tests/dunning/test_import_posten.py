"""M6-06/07: Offene Posten aus Excel nur im Cockpit; Mahnen ohne Lexware, Mahnschreiben der App (H6–H8, ADR-008)."""

from datetime import date
from decimal import Decimal

import pytest
from django.core import mail

from audit.models import Protokolleintrag
from datenimport import services
from datenimport.models import ImportVorgang
from datenimport.services import ImportNichtMoeglich
from dunning.freigabe import freigeben
from dunning.mail import ANHANG_SATZ
from dunning.models import Mahnvorschlag
from dunning.vorschlaege import HINWEIS_IMPORT, vorschlagslauf
from jobs.queue import enqueue
from ledger.models import Beleg, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.dunning.conftest import versendet

pytestmark = pytest.mark.django_db
D = Decimal

POSTEN_CSV = (
    "Rechnungsnr;Datum;Fällig am;Kunde;Kd-Nr;Betrag;Bezahlt\n"
    "2024-117;01.09.2026;15.09.2026;Bau AG;;1.190,00;\n"  # neu, überfällig, Kunde über Namen
    "2024-118;20.10.2026;30.11.2026;;K-9;500,00;100,00\n"  # neu, Teilzahlung, Kunde über Excel-Nummer
    "2024-119;01.08.2026;15.08.2026;Bau AG;;300,00;300,00\n"  # bezahlt
    "RE1001;01.08.2026;15.08.2026;Bau AG;;100,00;\n"  # Dublette (aus Lexware)
    "2024-120;01.08.2026;15.08.2026;Unbekannt GmbH;;100,00;\n"  # Fehler: Kunde fehlt
    "2024-121;01.08.2026;15.07.2026;Bau AG;;100,00;\n"  # Fehler: Fälligkeit vor Datum
    "2024-122;01.08.2026;15.08.2026;Bau AG;;100,00;200,00\n"  # mehr bezahlt als berechnet
).encode()


@pytest.fixture
def kunden(firma):
    bau = Kontakt.objects.create(
        firma=firma,
        extern_id="kon-bau",
        name="Bau AG",
        email="rechnung@bau-ag.example",
        kundentyp="unternehmer",
        adresse="Bahnhofstr. 1\n10115 Berlin",
    )
    dach = Kontakt.objects.create(
        firma=firma, extern_id="kon-dach", name="Dach KG", email="", kundentyp="unternehmer", excel_nummer="K-9"
    )
    Beleg.objects.create(
        firma=firma,
        extern_id="inv-1001",
        nummer="RE1001",
        kontakt=bau,
        kontakt_name=bau.name,
        belegdatum=date(2026, 10, 1),
        faellig_am=date(2026, 10, 15),
        brutto=D("100.00"),
        offen=D("100.00"),
        status="ueberfaellig",
    )
    return bau, dach


@pytest.fixture
def umgebung(firma, inhaber, lexware_api, ohne_warten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.strasse, firma.plz, firma.ort = "Malerweg 5", "10117", "Berlin"
    firma.save()
    return lexware_api


def _importieren(firma, inhaber):
    vorgang = services.hochladen(firma, inhaber, "posten", "offen.csv", POSTEN_CSV)
    assert services.zuordnung_speichern(vorgang, vorgang.zuordnung, {}, False) == []
    return vorgang


def test_vorschau_offener_posten(firma, inhaber, kunden, heute):
    vorgang = _importieren(firma, inhaber)
    zeilen = {z["nr"]: z for z in vorgang.vorschau}
    assert zeilen[2]["status"] == "neu" and zeilen[2]["daten"]["ueberfaellig"] is True
    assert zeilen[3]["status"] == "neu" and zeilen[3]["daten"]["offen"] == "400.00"
    assert zeilen[3]["daten"]["kunde"] == "Dach KG"
    assert zeilen[4]["status"] == "bezahlt"
    assert zeilen[5]["status"] == "dublette" and "schon im Cockpit" in zeilen[5]["grund"]
    assert zeilen[6]["status"] == "fehler" and "nicht in Lexware" in zeilen[6]["grund"]
    assert zeilen[7]["status"] == "fehler" and "Fälligkeit" in zeilen[7]["grund"]
    assert zeilen[8]["status"] == "bezahlt"  # mehr bezahlt als berechnet: nichts mehr offen


def test_mehrdeutiger_kunde_ist_fehler(firma, inhaber, kunden, heute):
    Kontakt.objects.create(firma=firma, extern_id="kon-bau-2", name="bau ag")
    vorgang = _importieren(firma, inhaber)
    assert {z["nr"]: z["status"] for z in vorgang.vorschau}[2] == "fehler"
    assert "mehrdeutig" in vorgang.vorschau[0]["grund"]


def test_posten_nur_im_cockpit_ohne_lexware(firma, inhaber, kunden, umgebung):
    vorgang = _importieren(firma, inhaber)
    services.freigeben(vorgang, inhaber)  # ohne Verbindung möglich: Lexware wird nicht berührt
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG and vorgang.ergebnis["angelegt"] == 2
    alt = Beleg.objects.get(firma=firma, nummer="2024-117")
    assert alt.quelle == "import" and alt.importiert and alt.import_vorgang == vorgang
    assert alt.status == "ueberfaellig" and alt.offen == D("1190.00") and alt.kontakt == kunden[0]
    teil = Beleg.objects.get(firma=firma, nummer="2024-118")
    assert teil.status == "offen" and teil.offen == D("400.00") and teil.brutto == D("500.00")
    assert not Beleg.objects.filter(nummer="2024-119").exists()
    assert umgebung.calls.call_count == 0
    assert Protokolleintrag.objects.filter(ereignis="import.fertig").count() == 1


def test_abgleich_laesst_importierte_posten_in_ruhe(firma, inhaber, kunden, umgebung, verbindung, worker):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    enqueue("ledger.nachtabgleich", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    alt = Beleg.objects.get(firma=firma, nummer="2024-117")
    assert alt.status == "ueberfaellig" and alt.offen == D("1190.00")
    assert not any("import-" in str(c.request.url) for c in umgebung.calls)


def test_status_wird_mit_faelligkeit_ueberfaellig(firma, inhaber, kunden, heute):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    teil = Beleg.objects.get(firma=firma, nummer="2024-118")
    import time_machine

    with time_machine.travel(date(2026, 12, 2), tick=False):
        assert services.importierte_status_aktualisieren(firma) == 1
    teil.refresh_from_db()
    assert teil.status == "ueberfaellig"


def test_zahlung_von_hand(firma, inhaber, kunden, heute):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    teil = Beleg.objects.get(firma=firma, nummer="2024-118")
    services.zahlung_eintragen(teil, inhaber, None, D("150.00"))
    teil.refresh_from_db()
    assert teil.offen == D("150.00") and teil.status == "offen"
    with pytest.raises(ImportNichtMoeglich):
        services.zahlung_eintragen(teil, inhaber, None, D("600.00"))
    services.zahlung_eintragen(teil, inhaber, date(2026, 11, 4), None)
    teil.refresh_from_db()
    assert teil.status == "bezahlt" and teil.offen == 0 and teil.bezahlt_am == date(2026, 11, 4)
    assert Protokolleintrag.objects.filter(ereignis="beleg.zahlung_manuell", nutzer=inhaber).count() == 2
    with pytest.raises(ImportNichtMoeglich, match="aus Lexware"):
        services.zahlung_eintragen(Beleg.objects.get(nummer="RE1001"), inhaber, date(2026, 11, 4), None)


def _vorschlag(firma, nummer):
    return next(v for v in vorschlagslauf(firma).neu if v.beleg.nummer == nummer)


def _senden(firma, inhaber, vorschlag, worker):
    freigeben(firma, inhaber, [vorschlag.pk])
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    return vorschlag


def test_erinnerung_ohne_anhang_und_ohne_lexware(firma, inhaber, kunden, umgebung, verbindung, worker):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    vorschlag = _vorschlag(firma, "2024-117")
    assert HINWEIS_IMPORT in vorschlag.hinweise
    vorschlag = _senden(firma, inhaber, vorschlag, worker)
    assert vorschlag.status == "versendet"
    nachricht = mail.outbox[0]
    assert nachricht.attachments == []
    assert ANHANG_SATZ.strip() not in nachricht.body
    assert "2024-117" in nachricht.subject
    assert umgebung.calls.call_count == 0  # kein Frische-Check in Lexware, kein PDF aus Lexware


def test_mahnung_mit_mahnschreiben_der_app(firma, inhaber, kunden, umgebung, verbindung, worker):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    beleg = Beleg.objects.get(firma=firma, nummer="2024-117")
    versendet(beleg, 0, tage_her=30)
    vorschlag = _senden(firma, inhaber, _vorschlag(firma, "2024-117"), worker)
    assert vorschlag.stufe == 1 and vorschlag.status == "versendet"
    name, inhalt, typ = mail.outbox[0].attachments[0]
    assert name == "Mahnung_2024-117.pdf" and typ == "application/pdf" and inhalt.startswith(b"%PDF")
    assert umgebung.calls.call_count == 0  # keine Mahnung in Lexware: Lexware kennt die Rechnung nicht
    assert not vorschlag.lexware_dunning_id


def test_postversand_ohne_mail_adresse(firma, inhaber, kunden, umgebung, worker):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    # Dach KG hat keine E-Mail-Adresse; Stufe 0 per Post bekommt das Mahnschreiben als Brief
    teil = Beleg.objects.get(firma=firma, nummer="2024-118")
    teil.faellig_am = date(2026, 10, 20)
    teil.save(update_fields=["faellig_am"])
    vorschlag = _senden(firma, inhaber, _vorschlag(firma, "2024-118"), worker)
    assert vorschlag.status == "post_bereit"
    assert vorschlag.pdf_name == "Zahlungserinnerung_2024-118.pdf"
    assert bytes(vorschlag.pdf).startswith(b"%PDF")
    assert mail.outbox == []


def test_frische_check_aus_dem_cockpit(firma, inhaber, kunden, umgebung, worker):
    services.freigeben(_importieren(firma, inhaber), inhaber)
    vorschlag = _vorschlag(firma, "2024-117")
    beleg = vorschlag.beleg
    freigeben(firma, inhaber, [vorschlag.pk])
    services.zahlung_eintragen(beleg, inhaber, None, D("190.00"))  # Teilzahlung nach der Freigabe
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "vorgeschlagen" and vorschlag.offen_betrag == D("190.00")
    assert "im Cockpit geändert" in vorschlag.hinweise[0]
    freigeben(firma, inhaber, [vorschlag.pk])
    services.zahlung_eintragen(beleg, inhaber, date(2026, 11, 5), None)
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "verworfen" and mail.outbox == []
    assert Mahnvorschlag.objects.filter(status="versendet").count() == 0


def test_mahnschreiben_inhalt(firma, inhaber, kunden, umgebung):
    import io

    from pypdf import PdfReader

    from dunning import mahnschreiben

    services.freigeben(_importieren(firma, inhaber), inhaber)
    beleg = Beleg.objects.get(firma=firma, nummer="2024-117")
    versendet(beleg, 0, tage_her=30)
    vorschlag = _vorschlag(firma, "2024-117")
    text = PdfReader(io.BytesIO(mahnschreiben.pdf(vorschlag))).pages[0].extract_text()
    assert "Bahnhofstr. 1" in text and "10115 Berlin" in text
    assert "Malerweg 5" in text and "05.11.2026" in text
    assert "2024-117" in text and "1.190,00" in text
