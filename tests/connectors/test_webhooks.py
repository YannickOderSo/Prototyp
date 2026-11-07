"""M1-08: Webhooks registrieren und empfangen, Signaturprüfung, idempotente Verarbeitung (B3)."""

import base64
import json
from datetime import date
from decimal import Decimal

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from django.core import mail
from django.test import override_settings
from django.urls import reverse

from connectors import signatur
from connectors.models import Verbindung, WebhookEreignis
from jobs.models import Job
from jobs.queue import enqueue
from ledger.models import Beleg, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.lexware_mock import BASIS, FIXTURES, lade

ORG = "aa93e8a8-2aa3-470b-b914-caad8a255dd8"

_privat = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PEM = _privat.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def signieren(body: bytes) -> str:
    return base64.b64encode(_privat.sign(body, padding.PKCS1v15(), hashes.SHA512())).decode()


@pytest.fixture
def test_schluessel(monkeypatch):
    import connectors.webhooks

    monkeypatch.setattr(
        connectors.webhooks, "signatur_gueltig", lambda b, s: signatur.signatur_gueltig(b, s, pem=TEST_PEM)
    )


def _senden(client, verbindung, typ, resource_id, zeit="2026-11-05T10:00:00.000+01:00", org=ORG, sig=None):
    body = json.dumps(
        {"organizationId": org, "eventType": typ, "resourceId": resource_id, "eventDate": zeit}, separators=(",", ":")
    ).encode()
    return client.post(
        reverse("hooks:lexware", args=[verbindung.webhook_token]),
        data=body,
        content_type="application/json",
        HTTP_X_LXO_SIGNATURE=sig if sig is not None else signieren(body),
    )


@pytest.fixture
def lex_verbindung(verbindung):
    Verbindung.objects.filter(pk=verbindung.pk).update(organisation_id=ORG)
    verbindung.refresh_from_db()
    return verbindung


def test_signatur_mit_offiziellem_doku_beispiel():
    body = (FIXTURES / "webhook_sample_payload.json").read_bytes()
    sig = (FIXTURES / "webhook_sample_signature_base64").read_text()
    assert signatur.signatur_gueltig(body, sig)
    assert not signatur.signatur_gueltig(body.replace(b"contact.created", b"contact.changed"), sig)
    assert not signatur.signatur_gueltig(body, "")
    assert not signatur.signatur_gueltig(body, "kein-base64!!")


def test_eingebauter_schluessel_entspricht_doku():
    assert (FIXTURES / "webhook_public_key.pub").read_bytes().strip() == signatur.LEXWARE_WEBHOOK_SCHLUESSEL.strip()


@pytest.mark.django_db
def test_gueltiger_webhook_plant_abgleich_und_ist_idempotent(client, lex_verbindung, test_schluessel):
    antwort = _senden(client, lex_verbindung, "payment.changed", "inv-0001")
    assert antwort.status_code == 202
    assert WebhookEreignis.objects.count() == 1
    assert Job.objects.filter(typ="ledger.beleg_abgleichen").count() == 1
    # identisches Ereignis erneut (Lexware wiederholt bei Zeitüberschreitung)
    assert _senden(client, lex_verbindung, "payment.changed", "inv-0001").status_code == 200
    assert WebhookEreignis.objects.count() == 1
    assert Job.objects.filter(typ="ledger.beleg_abgleichen").count() == 1
    # neues Ereignis zum selben Beleg, solange der Job noch wartet: kein zweiter Job
    _senden(client, lex_verbindung, "invoice.status.changed", "inv-0001", zeit="2026-11-05T10:00:05.000+01:00")
    assert WebhookEreignis.objects.count() == 2
    assert Job.objects.filter(typ="ledger.beleg_abgleichen").count() == 1


@pytest.mark.django_db
def test_ungueltige_signatur_wird_verworfen(client, lex_verbindung, test_schluessel):
    assert (
        _senden(client, lex_verbindung, "payment.changed", "inv-0001", sig=signieren(b"anderer body")).status_code
        == 401
    )
    assert _senden(client, lex_verbindung, "payment.changed", "inv-0001", sig="").status_code == 401
    assert not WebhookEreignis.objects.exists()
    assert not Job.objects.exists()


@pytest.mark.django_db
def test_echter_lexware_schluessel_lehnt_selbst_signierte_ab(client, lex_verbindung):
    assert _senden(client, lex_verbindung, "payment.changed", "inv-0001").status_code == 401


@pytest.mark.django_db
def test_fremde_organisation_und_unbekanntes_token(client, lex_verbindung, test_schluessel):
    assert _senden(client, lex_verbindung, "payment.changed", "x", org="fremd").status_code == 401
    antwort = client.post(reverse("hooks:lexware", args=["gibt-es-nicht"]), data=b"{}", content_type="application/json")
    assert antwort.status_code == 404
    assert not WebhookEreignis.objects.exists()


@pytest.mark.django_db
def test_kaputtes_json(client, lex_verbindung, test_schluessel):
    body = b"kein json"
    antwort = client.post(
        reverse("hooks:lexware", args=[lex_verbindung.webhook_token]),
        data=body,
        content_type="application/json",
        HTTP_X_LXO_SIGNATURE=signieren(body),
    )
    assert antwort.status_code == 400


@pytest.mark.django_db
def test_nur_post(client, lex_verbindung):
    assert client.get(reverse("hooks:lexware", args=[lex_verbindung.webhook_token])).status_code == 405


@pytest.mark.django_db
def test_bezahlte_rechnung_verschwindet_nach_webhook_aus_offen(
    client, firma, lex_verbindung, test_schluessel, lexware_api, ohne_warten, worker
):
    """B3: Zahlung in Lexware → Webhook → Job lädt nach → Posten nicht mehr offen (Worker-Takt ≤ 1 s)."""
    enqueue("ledger.erstimport", {"verbindung_id": lex_verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    assert Beleg.objects.get(firma=firma, extern_id="inv-0001").ist_offen
    lexware_api.get(f"{BASIS}/v1/invoices/inv-0001").respond(
        200, json={**lade("invoice_0001.json"), "voucherStatus": "paid"}
    )
    lexware_api.get(f"{BASIS}/v1/payments/inv-0001").respond(200, json=lade("payment_paid.json"))
    _senden(client, lex_verbindung, "payment.changed", "inv-0001")
    alle_jobs_ausfuehren(worker)
    beleg = Beleg.objects.get(firma=firma, extern_id="inv-0001")
    assert not beleg.ist_offen
    assert beleg.offen == Decimal("0.00")
    assert beleg.bezahlt_am == date(2026, 6, 30)
    assert WebhookEreignis.objects.get().verarbeitet_am is not None


@pytest.mark.django_db
def test_geloeschte_rechnung(client, firma, lex_verbindung, test_schluessel, lexware_api, ohne_warten, worker):
    Beleg.objects.create(firma=firma, extern_id="weg-1", offen=Decimal("10"), status="offen")
    lexware_api.get(f"{BASIS}/v1/invoices/weg-1").respond(404)
    lexware_api.get(f"{BASIS}/v1/down-payment-invoices/weg-1").respond(404)
    _senden(client, lex_verbindung, "invoice.deleted", "weg-1")
    alle_jobs_ausfuehren(worker)
    assert not Beleg.objects.get(extern_id="weg-1").ist_offen


@pytest.mark.django_db
def test_kontakt_geaendert(client, firma, lex_verbindung, test_schluessel, lexware_api, ohne_warten, worker):
    Kontakt.objects.create(firma=firma, extern_id="kon-privat", name="Alt", kundentyp="privat")
    lexware_api.get(f"{BASIS}/v1/contacts/kon-privat").respond(200, json=lade("contacts_0.json")["content"][1])
    _senden(client, lex_verbindung, "contact.changed", "kon-privat")
    alle_jobs_ausfuehren(worker)
    kontakt = Kontakt.objects.get(extern_id="kon-privat")
    assert kontakt.name == "Erika Musterfrau"
    assert kontakt.kundentyp == "privat"


@pytest.mark.django_db
def test_token_widerrufen_trennt_und_benachrichtigt_inhaber(
    client, firma, inhaber, lex_verbindung, test_schluessel, worker
):
    _senden(client, lex_verbindung, "token.revoked", "3dea098b")
    alle_jobs_ausfuehren(worker)
    lex_verbindung.refresh_from_db()
    assert lex_verbindung.status == Verbindung.Status.GETRENNT
    assert lex_verbindung.schluessel_verschluesselt == ""
    assert mail.outbox[0].to == [inhaber.email]
    assert "widerrufen" in mail.outbox[0].body


@pytest.mark.django_db
@override_settings(BASIS_URL="https://cockpit.example")
def test_webhooks_werden_nach_erstimport_registriert(firma, lex_verbindung, lexware_api, ohne_warten, worker):
    route = lexware_api.post(f"{BASIS}/v1/event-subscriptions").respond(
        201, json=lade("event_subscription_created.json")
    )
    enqueue("ledger.erstimport", {"verbindung_id": lex_verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    lex_verbindung.refresh_from_db()
    assert len(lex_verbindung.webhook_ids) == route.call_count >= 9
    url = json.loads(route.calls.last.request.content)["callbackUrl"]
    assert url == f"https://cockpit.example/hooks/lexware/{lex_verbindung.webhook_token}/"


@pytest.mark.django_db
def test_ohne_https_keine_registrierung(firma, lex_verbindung, lexware_api, ohne_warten, worker):
    route = lexware_api.post(f"{BASIS}/v1/event-subscriptions").respond(201, json={})
    enqueue("connectors.webhooks_registrieren", {"verbindung_id": lex_verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    assert route.call_count == 0


@pytest.mark.django_db
def test_webhook_rate_limit(client, lex_verbindung, test_schluessel):
    from datetime import UTC, datetime

    import time_machine
    from django.core.cache import cache

    cache.clear()
    # Zeit anhalten: Das 15-Minuten-Fenster von django-ratelimit beginnt je Schlüssel zu einer zufälligen Minute.
    # Lief der Test über diese Grenze, begann die Zählung neu und der Test schlug gelegentlich fehl (CI am 7.11.2026).
    with time_machine.travel(datetime(2026, 11, 7, 12, 0, tzinfo=UTC), tick=False):
        for i in range(600):
            _senden(client, lex_verbindung, "contact.changed", f"k{i}")
        assert _senden(client, lex_verbindung, "contact.changed", "k-letzter").status_code == 429
