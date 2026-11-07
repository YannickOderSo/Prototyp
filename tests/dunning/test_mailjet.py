"""p3-bounce: Zustellmeldungen von Mailjet (Event API) dem Versand zuordnen.

Die Beispiel-Ereignisse folgen den Mustern der Mailjet-Doku (dev.mailjet.com/docs/email-api/webhooks/event-types,
gelesen am 7. November 2026). Ein echtes Ereignis aus einem Testversand steht noch aus (Echtlauf p4-mail)."""

import json
from unittest import mock

import pytest
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.mail import MailInhalt
from dunning.mailversand import senden
from dunning.models import Angebotserinnerung, SmtpZugang, Versand
from ledger.models import Beleg

pytestmark = pytest.mark.django_db
URL_TOKEN = "geheimes-token"


def _ereignis(event, custom_id, **mehr):
    basis = {
        "event": event,
        "time": 1430812195,
        "MessageID": 13792286917004336,
        "Message_GUID": "1ab23cd4-e567-8901-2345-6789f0gh1i2j",
        "email": "kunde@example.org",
        "mj_campaign_id": 0,
        "mj_contact_id": 0,
        "customcampaign": "",
        "CustomID": custom_id,
        "Payload": "",
    }
    return {**basis, **mehr}


@pytest.fixture
def url(settings):
    settings.ZUSTELLUNG_WEBHOOK_TOKEN = URL_TOKEN
    return reverse("hooks:zustellung", args=[URL_TOKEN])


@pytest.fixture
def versand(firma):
    return Versand.objects.create(
        firma=firma, empfaenger="kunde@example.org", betreff="1. Mahnung zu RE1", text="…", message_id="<abc@cockpit>"
    )


def test_gruppierte_ereignisse(client, url, firma, versand):
    angebot = Beleg.objects.create(firma=firma, extern_id="q1", art="angebot", nummer="AN-1", status="offen")
    erinnerung = Angebotserinnerung.objects.create(
        firma=firma, beleg=angebot, status="versendet", message_id="<angebot@cockpit>"
    )
    ereignisse = [
        _ereignis("sent", "abc@cockpit", smtp_reply="sent (250 2.0.0 OK)"),
        _ereignis(
            "bounce",
            "abc@cockpit",
            blocked=False,
            hard_bounce=True,
            error_related_to="recipient",
            error="user unknown",
            comment="Host or domain name not found",
        ),
        _ereignis("spam", "angebot@cockpit", source="JMRPP"),
        _ereignis("blocked", "", error_related_to="recipient", error="preblocked"),  # ohne CustomID: nicht zuordenbar
        _ereignis("unsub", "abc@cockpit", mj_list_id=1),
    ]
    antwort = client.post(url, json.dumps(ereignisse), content_type="application/json")
    assert antwort.status_code == 200  # genau 200, sonst wiederholt Mailjet
    versand.refresh_from_db()
    assert versand.zustellfehler == "hard_bounce: recipient / user unknown / Host or domain name not found"
    erinnerung.refresh_from_db()
    assert erinnerung.status == "fehler" and "complaint: JMRPP" in erinnerung.fehler
    assert Protokolleintrag.objects.filter(ereignis="mahnung.zustellfehler").count() == 1
    assert Protokolleintrag.objects.filter(ereignis="angebot.zustellfehler").count() == 1


def test_einzelnes_ereignis_und_soft_bounce(client, url, versand):
    weich = _ereignis("bounce", "abc@cockpit", hard_bounce=False, error_related_to="mailbox", error="full")
    assert client.post(url, json.dumps(weich), content_type="application/json").status_code == 200
    versand.refresh_from_db()
    assert versand.zustellfehler == "soft_bounce: mailbox / full"
    blockiert = _ereignis("blocked", "abc@cockpit", error_related_to="recipient", error="preblocked")
    client.post(url, json.dumps(blockiert), content_type="application/json")
    versand.refresh_from_db()
    assert versand.zustellfehler == "rejected: recipient / preblocked"


def test_unbekannte_formate(client, url):
    assert client.post(url, json.dumps({"irgendwas": 1}), content_type="application/json").status_code == 400
    assert client.post(url, json.dumps("text"), content_type="application/json").status_code == 400
    zu_viele = [_ereignis("sent", "x")] * 501
    assert client.post(url, json.dumps(zu_viele), content_type="application/json").status_code == 400
    # unbekannte CustomID: bestätigen, nichts ändern (sonst wiederholt Mailjet einen Tag lang)
    fremd = _ereignis("bounce", "fremd@x", hard_bounce=True)
    assert client.post(url, json.dumps(fremd), content_type="application/json").status_code == 200
    assert not Protokolleintrag.objects.filter(ereignis="mahnung.zustellfehler").exists()


def _mail():
    return MailInhalt(
        absender="Malerbetrieb Muster <mahnung@belegfluss.example>",
        empfaenger="kunde@example.org",
        reply_to="buero@muster.example",
        bcc="",
        betreff="Zahlungserinnerung",
        text="…",
        anhang_name="",
    )


@override_settings(MAILVERSAND_ANBIETER="mailjet", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_custom_id_nur_ueber_plattform_smtp(firma):
    message_id = senden(firma, _mail(), None)
    assert mail.outbox[0].extra_headers["X-MJ-CustomID"] == message_id.strip("<>")
    SmtpZugang.objects.create(firma=firma, host="smtp.muster.example", port=587, aktiv=True)
    from django.core.mail import get_connection

    with mock.patch(
        "dunning.mailversand.smtp_verbindung",
        lambda _z: get_connection("django.core.mail.backends.locmem.EmailBackend"),
    ):
        senden(firma, _mail(), None)
    assert "X-MJ-CustomID" not in mail.outbox[1].extra_headers  # eigenes SMTP der Firma: kein Mailjet


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_ohne_mailjet_kein_kopf(firma, settings):
    settings.MAILVERSAND_ANBIETER = ""
    senden(firma, _mail(), None)
    assert "X-MJ-CustomID" not in mail.outbox[0].extra_headers
