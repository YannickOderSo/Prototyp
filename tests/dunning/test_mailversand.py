"""M2-06: Versand über Plattform-SMTP oder eigenes SMTP der Firma, Zustellfehler, Tests gegen Mailpit."""

import json

import pytest
from django.test import override_settings
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.freigabe import freigeben
from dunning.mail import inhalt
from dunning.mailversand import absender_adresse, verbindung_fuer
from dunning.models import SmtpZugang, Versand
from dunning.vorschlaege import vorschlagslauf
from tests import mailpit
from tests.conftest import alle_jobs_ausfuehren
from tests.dunning.conftest import versendet
from tests.lexware_mock import BASIS, lade, pdf

pytestmark = pytest.mark.django_db


@pytest.fixture
def mahnung_bereit(firma, verbindung, inhaber, posten, lexware_api, ohne_warten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.bankverbindung = "IBAN DE12 3456 7890 1234 5678 90"
    firma.save()
    beleg = posten(tage=40, offen="1000.00", extern_id="inv-0001")
    versendet(beleg, 0, tage_her=30)
    lexware_api.get(f"{BASIS}/v1/payments/inv-0001").respond(
        200, json={"openAmount": 1000.0, "voucherStatus": "open", "voucherType": "invoice", "paymentItems": []}
    )
    lexware_api.post(f"{BASIS}/v1/dunnings").respond(201, json={**lade("created.json"), "id": "mahn-1"})
    lexware_api.get(f"{BASIS}/v1/dunnings/mahn-1/file").respond(200, content=pdf())
    if mailpit.MAILPIT_URL:
        lexware_api.route(url__startswith=mailpit.MAILPIT_URL).pass_through()
    return vorschlagslauf(firma).neu[0]


def test_plattform_absender_mit_firmenname(firma):
    assert absender_adresse(firma) == "cockpit@localhost"
    from django.core.mail.backends.locmem import EmailBackend

    assert isinstance(verbindung_fuer(firma), EmailBackend)


def test_eigenes_smtp_absender_und_verbindung(firma):
    from cockpit.krypto import verschluesseln

    SmtpZugang.objects.create(
        firma=firma,
        host="smtp.muster.example",
        port=465,
        benutzer="u",
        passwort_verschluesselt=verschluesseln("p"),
        ssl=True,
        absender_adresse="mahnung@muster.example",
        aktiv=True,
    )
    assert absender_adresse(firma) == "mahnung@muster.example"
    verbindung = verbindung_fuer(firma)
    assert (verbindung.host, verbindung.port, verbindung.use_ssl, verbindung.use_tls, verbindung.password) == (
        "smtp.muster.example",
        465,
        True,
        False,
        "p",
    )


def test_smtp_seite_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("dunning:smtp")).status_code == 403


def test_smtp_aktivieren_scheitert_ohne_erreichbaren_server(client_inhaber, firma):
    antwort = client_inhaber.post(
        reverse("dunning:smtp"),
        {
            "aktiv": "on",
            "host": "127.0.0.1",
            "port": 9,
            "benutzer": "x",
            "passwort": "geheim",
            "absender_adresse": "a@muster.example",
        },
    )
    assert antwort.status_code == 200
    assert "Testmail konnte nicht gesendet werden" in antwort.content.decode()
    assert not SmtpZugang.objects.filter(firma=firma, aktiv=True).exists()


def test_smtp_ohne_aktiv_speichern_und_passwort_verschluesseln(client_inhaber, firma):
    client_inhaber.post(
        reverse("dunning:smtp"),
        {
            "host": "smtp.muster.example",
            "port": 587,
            "benutzer": "x",
            "passwort": "geheim",
            "starttls": "on",
            "absender_adresse": "a@muster.example",
        },
    )
    zugang = SmtpZugang.objects.get(firma=firma)
    assert "geheim" not in zugang.passwort_verschluesselt
    assert not zugang.aktiv
    assert Protokolleintrag.objects.filter(ereignis="einstellung.smtp_geaendert").exists()


@override_settings(ZUSTELLUNG_WEBHOOK_TOKEN="geheimes-token")
def test_zustellfehler_webhook(client, client_inhaber, firma):
    versand = Versand.objects.create(
        firma=firma, empfaenger="x@kunde.example", betreff="1. Mahnung zu RE1", text="…", message_id="<abc@cockpit>"
    )
    url = reverse("hooks:zustellung", args=["geheimes-token"])
    assert (
        client.post(reverse("hooks:zustellung", args=["falsch"]), "{}", content_type="application/json").status_code
        == 404
    )
    assert client.post(url, "kein json", content_type="application/json").status_code == 400
    assert (
        client.post(
            url, json.dumps({"message_id": "abc@cockpit", "ereignis": "delivered"}), content_type="application/json"
        ).status_code
        == 204
    )
    versand.refresh_from_db()
    assert versand.zustellfehler == ""
    client.post(
        url,
        json.dumps({"message_id": "abc@cockpit", "ereignis": "bounce", "grund": "550 Mailbox unbekannt"}),
        content_type="application/json",
    )
    versand.refresh_from_db()
    assert versand.zustellfehler == "bounce: 550 Mailbox unbekannt"
    assert Protokolleintrag.objects.filter(ereignis="mahnung.zustellfehler").exists()
    assert "550 Mailbox unbekannt" in client_inhaber.get(reverse("dunning:freigabe")).content.decode()


def test_zustellfehler_webhook_ohne_token_konfiguration(client):
    assert (
        client.post(reverse("hooks:zustellung", args=["x"]), "{}", content_type="application/json").status_code == 404
    )


# ------------------------------------------------------------------ gegen Mailpit (lokal und in CI)
@pytest.mark.mailpit
@mailpit.braucht_mailpit
def test_mahnung_kommt_in_mailpit_an(firma, inhaber, mahnung_bereit, worker):
    mailpit.leeren()
    erwartet = inhalt(mahnung_bereit)
    with override_settings(**mailpit.smtp_einstellungen()):
        freigeben(firma, inhaber, [mahnung_bereit.pk])
        alle_jobs_ausfuehren(worker)
    mahnung_bereit.refresh_from_db()
    assert mahnung_bereit.status == "versendet"
    (nachricht,) = mailpit.nachrichten()
    assert nachricht["Subject"] == erwartet.betreff
    assert nachricht["From"] == {"Name": "Malerbetrieb Muster", "Address": "cockpit@localhost"}
    assert nachricht["To"] == [{"Name": "", "Address": "kunde@example.org"}]
    assert nachricht["ReplyTo"] == [{"Name": "", "Address": "buero@muster.example"}]
    text = nachricht["Text"]
    assert "Offener Rechnungsbetrag: 1.000,00 €" in text
    assert "Verzugspauschale (§ 288 Abs. 5 BGB): 40,00 €" in text
    assert "Gesamtbetrag: 1.048,07 €" in text
    assert "IBAN DE12" in text
    (anhang,) = nachricht["Attachments"]
    assert anhang["FileName"] == erwartet.anhang_name
    assert anhang["ContentType"] == "application/pdf"
    kopf = mailpit.kopfzeilen(nachricht["ID"])
    assert kopf["Message-Id"][0] == Versand.objects.get().message_id
    assert kopf["Auto-Submitted"] == ["auto-generated"]


@pytest.mark.mailpit
@mailpit.braucht_mailpit
def test_eigenes_smtp_ueber_mailpit(client_inhaber, firma, inhaber, mahnung_bereit, worker):
    mailpit.leeren()
    antwort = client_inhaber.post(
        reverse("dunning:smtp"),
        {
            "aktiv": "on",
            "host": mailpit.SMTP_HOST,
            "port": mailpit.SMTP_PORT,
            "benutzer": "",
            "absender_adresse": "mahnung@muster.example",
        },
    )
    assert antwort.status_code == 302
    (testmail,) = mailpit.nachrichten()
    assert testmail["Subject"] == "Testmail aus Belegfluss"
    assert testmail["To"][0]["Address"] == inhaber.email
    mailpit.leeren()
    freigeben(firma, inhaber, [mahnung_bereit.pk])
    alle_jobs_ausfuehren(worker)  # Plattform-Backend ist locmem; die Mail geht über das eigene SMTP (Mailpit)
    (nachricht,) = mailpit.nachrichten()
    assert nachricht["From"] == {"Name": "Malerbetrieb Muster", "Address": "mahnung@muster.example"}
