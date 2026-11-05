"""Playwright: die drei Hauptabläufe auf dem Handy-Viewport 390 × 844 (Teststrategie.md).

1. Lexware verbinden: Anmeldung mit 2FA, Schlüssel eintragen, Erstimport, offene Posten nach Alter.
2. Mahnungen freigeben: Freigeber meldet sich mit 2FA an, gibt frei, Mail mit PDF geht hinaus.
3. Sprachmemo zu Entwurf: Aufnahme im Browser (Fake-Mikrofon), Transkript prüfen, Entwurf prüfen,
   freigeben, Rechnungsentwurf in Lexware (nie finalize).

Lexware, Mistral und die KI sind nachgebaut (respx bzw. Fake-Client); Jobs führt der Test selbst aus,
weil im Test kein Worker-Prozess läuft. Mails gehen an das locmem-Backend.
"""

import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts import totp
from accounts.models import ZweiFaktor
from cockpit.krypto import verschluesseln
from tests.conftest import PASSWORT, alle_jobs_ausfuehren
from tests.e2e.conftest import kein_horizontales_scrollen
from tests.ki_fake import antwort, ergebnis
from tests.lexware_mock import BASIS, lade, pdf

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True, serialized_rollback=True)]


def _zweiter_faktor(nutzer) -> str:
    geheimnis = totp.neues_geheimnis()
    ZweiFaktor.objects.create(
        nutzer=nutzer, geheimnis_verschluesselt=verschluesseln(geheimnis), eingerichtet_am=timezone.now()
    )
    return geheimnis


def anmelden(seite, live_server, nutzer):
    """Anmeldung über die Oberfläche: Passwort, dann Code aus der Authenticator-App."""
    geheimnis = _zweiter_faktor(nutzer)
    seite.goto(f"{live_server.url}/konto/anmelden/")
    kein_horizontales_scrollen(seite)
    seite.get_by_label("E-Mail-Adresse").fill(nutzer.email)
    seite.get_by_label("Passwort").fill(PASSWORT)
    seite.get_by_role("button", name="Weiter").click()
    seite.get_by_label("Code", exact=False).first.fill(totp.code_fuer_schritt(geheimnis, totp.aktueller_schritt()))
    seite.get_by_role("button", name="Anmelden").click()
    seite.wait_for_url(f"{live_server.url}/")


def test_lexware_verbinden(seite, live_server, firma, inhaber, lexware_api, ohne_warten, worker):
    anmelden(seite, live_server, inhaber)
    assert "Einrichtung starten" in seite.content()
    seite.get_by_role("link", name="Einrichtung starten").click()
    kein_horizontales_scrollen(seite)
    seite.get_by_role("link", name="Lexware verbinden").click()
    kein_horizontales_scrollen(seite)

    seite.get_by_label("API-Schlüssel", exact=False).fill("lexware-schluessel-des-piloten")
    seite.get_by_role("button", name="Schlüssel prüfen und speichern").click()
    seite.get_by_text("Verbunden mit Lexware").wait_for()

    # Der Worker läuft im Test nicht als eigener Prozess: Erstimport und Folge-Jobs hier ausführen
    alle_jobs_ausfuehren(worker)

    seite.goto(f"{live_server.url}/")
    kein_horizontales_scrollen(seite)
    inhalt = seite.content()
    assert "Noch keine Verbindung" not in inhalt
    assert "überfällig" in inhalt
    seite.goto(f"{live_server.url}/posten/")
    kein_horizontales_scrollen(seite)
    assert "RE1002" in seite.content()
    profil = [c for c in lexware_api.calls if c.request.url.path == "/v1/profile"]
    assert profil and profil[0].request.headers["Authorization"] == "Bearer lexware-schluessel-des-piloten"


@pytest.fixture
def mahnfall(firma, verbindung, lexware_api, ohne_warten):
    from dunning.models import Mahnplan
    from ledger.models import Beleg, Kontakt

    heute = timezone.localdate()
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.bankverbindung = "IBAN DE12 3456 7890 1234 5678 90"
    firma.save()
    verbindung.erstimport_fertig = timezone.now()
    verbindung.letzter_abgleich = timezone.now()
    verbindung.save()
    Mahnplan.objects.create(firma=firma)
    kontakt = Kontakt.objects.create(
        firma=firma, extern_id="k-bau", name="Bau AG", email="buchhaltung@bau.example", kundentyp="unternehmer"
    )
    Beleg.objects.create(
        firma=firma,
        extern_id="inv-e2e",
        nummer="RE2042",
        kontakt=kontakt,
        kontakt_name="Bau AG",
        belegdatum=heute - timedelta(days=24),
        faellig_am=heute - timedelta(days=10),
        offen=Decimal("1190.00"),
        brutto=Decimal("1190.00"),
        status="ueberfaellig",
    )
    zahlstatus = lexware_api.get(f"{BASIS}/v1/payments/inv-e2e").respond(
        200, json={"openAmount": 1190.0, "voucherStatus": "open", "voucherType": "invoice", "paymentItems": []}
    )
    lexware_api.get(f"{BASIS}/v1/invoices/inv-e2e").respond(200, json=lade("invoice_0001.json"))
    lexware_api.get(f"{BASIS}/v1/invoices/inv-e2e/file").respond(200, content=pdf())
    lexware_api.post(f"{BASIS}/v1/dunnings").respond(201, json={"id": "mahn-e2e"})
    lexware_api.get(f"{BASIS}/v1/dunnings/mahn-e2e/file").respond(200, content=pdf())
    return zahlstatus


def test_mahnungen_freigeben(seite, live_server, firma, freigeber, mahnfall, worker, mailoutbox):
    from dunning.models import Mahnvorschlag
    from dunning.vorschlaege import vorschlagslauf

    assert len(vorschlagslauf(firma).neu) == 1  # Lauf um 5 Uhr

    anmelden(seite, live_server, freigeber)
    seite.goto(f"{live_server.url}/mahnungen/")
    kein_horizontales_scrollen(seite)
    assert "RE2042" in seite.content() and "Bau AG" in seite.content()
    seite.locator(f"#v{Mahnvorschlag.objects.get().pk}").check()
    with seite.expect_navigation():
        seite.get_by_role("button", name="Markierte freigeben").click()
    kein_horizontales_scrollen(seite)
    vorschlag = Mahnvorschlag.objects.get()
    assert vorschlag.status == Mahnvorschlag.Status.FREIGEGEBEN
    assert vorschlag.freigegeben_von == freigeber

    alle_jobs_ausfuehren(worker)  # Versand mit Frische-Check

    vorschlag.refresh_from_db()
    assert vorschlag.status == Mahnvorschlag.Status.VERSENDET
    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert mail.to == ["buchhaltung@bau.example"]
    assert "RE2042" in mail.subject + mail.body
    assert any(name.endswith(".pdf") for name, *_ in mail.attachments)
    # Frische-Check: Zahlstatus unmittelbar vor dem Versand in Lexware abgefragt
    assert mahnfall.called
    # finalize prüft die Fixture lexware_api am Ende für alle Anfragen

    seite.reload()
    kein_horizontales_scrollen(seite)
    assert "versendet" in seite.content()


@pytest.fixture
def erfassung_bereit(firma, verbindung, settings, lexware_api, ohne_warten, ki):
    from ledger.models import Artikel, Kontakt

    settings.MISTRAL_API_KEY = "test-mistral"
    Kontakt.objects.create(firma=firma, extern_id="kon-bau", name="Bau AG", kundentyp="unternehmer")
    Artikel.objects.create(
        firma=firma,
        extern_id="art-maler-stunde",
        bezeichnung="Malerarbeiten Facharbeiter",
        einheit="Stunde",
        netto=Decimal("58.00"),
        steuersatz=Decimal("19"),
        typ="SERVICE",
    )
    lexware_api.post("https://api.mistral.ai/v1/audio/transcriptions").respond(
        200, json={"text": "Rechnung für Bau AG, zwölf Stunden Malerarbeiten vom 2. bis 4. November."}
    )
    rechnung = lexware_api.post(f"{BASIS}/v1/invoices").respond(201, json=lade("created.json"))
    ki(antwort(ergebnis()))
    return rechnung


def test_sprachmemo_zu_entwurf(seite, live_server, firma, inhaber, erfassung_bereit, worker):
    from capture.models import Erfassung

    anmelden(seite, live_server, inhaber)
    seite.goto(f"{live_server.url}/erfassen/neu/")
    kein_horizontales_scrollen(seite)
    seite.get_by_role("button", name="Aufnahme starten").click()
    seite.get_by_text("Aufnahme läuft … 0:02").wait_for()
    seite.get_by_role("button", name="Stopp und hochladen").click()
    seite.wait_for_url(re.compile(r"/erfassen/\d+/$"))
    erfassung = Erfassung.objects.get()
    assert erfassung.kanal == "aufnahme" and erfassung.erstellt_von == inhaber

    alle_jobs_ausfuehren(worker)  # Transkription (Mistral, EU), Audio wird gelöscht
    seite.reload()
    kein_horizontales_scrollen(seite)
    textfeld = seite.locator("#transkript")
    assert "zwölf Stunden Malerarbeiten" in textfeld.input_value()
    textfeld.fill(textfeld.input_value() + " Bitte 12 Stunden abrechnen.")
    with seite.expect_navigation():
        seite.get_by_role("button", name="Entwurf erzeugen").click()

    alle_jobs_ausfuehren(worker)  # Extraktion (KI liefert nur Struktur), Regeln setzen Preise aus Lexware
    seite.reload()
    kein_horizontales_scrollen(seite)
    inhalt = seite.content()
    assert "Malerarbeiten Facharbeiter" in inhalt and "58,00" in inhalt
    with seite.expect_navigation():
        seite.get_by_role("button", name="Freigeben und als Entwurf in Lexware anlegen").click()

    alle_jobs_ausfuehren(worker)  # Übertragung als Entwurf
    seite.reload()
    kein_horizontales_scrollen(seite)
    assert "in Lexware angelegt" in seite.content()
    erfassung.refresh_from_db()
    assert erfassung.status == Erfassung.Status.UEBERTRAGEN and erfassung.freigegeben_von == inhaber
    anfrage = erfassung_bereit.calls.last.request
    assert "finalize" not in str(anfrage.url)
    koerper = json.loads(anfrage.content)
    position = koerper["lineItems"][0]
    assert position["unitPrice"]["netAmount"] == 58.0 and position["quantity"] == 12
