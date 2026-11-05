"""Lexware-Webhooks empfangen (B3).

Ablauf: Token im Pfad → Rate-Limit → Signatur → Organisation passt → Ereignis einmalig speichern →
Job einreihen → sofort 202. Der Payload ist nur ein Hinweis: Daten werden immer nachgeladen.
"""

import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseNotFound
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.core import is_ratelimited

from jobs.queue import enqueue

from .models import Verbindung, WebhookEreignis
from .signatur import signatur_gueltig

log = logging.getLogger(__name__)

BELEG_EREIGNISSE = {
    "invoice.created",
    "invoice.changed",
    "invoice.status.changed",
    "invoice.deleted",
    "payment.changed",
    "down-payment-invoice.status.changed",
    "down-payment-invoice.changed",
    "down-payment-invoice.created",
    "down-payment-invoice.deleted",
}
KONTAKT_EREIGNISSE = {"contact.changed", "contact.created"}


def callback_url(verbindung: Verbindung) -> str:
    return settings.BASIS_URL + reverse("hooks:lexware", args=[verbindung.webhook_token])


def ereignis_einplanen(verbindung: Verbindung, ereignis: WebhookEreignis) -> None:
    payload = {"verbindung_id": verbindung.pk, "extern_id": ereignis.resource_id, "ereignis_id": ereignis.pk}
    typ = ereignis.event_typ
    if typ in BELEG_EREIGNISSE:
        enqueue(
            "ledger.beleg_abgleichen",
            payload,
            firma=verbindung.firma,
            eindeutig=f"beleg:{verbindung.pk}:{ereignis.resource_id}",
        )
    elif typ in KONTAKT_EREIGNISSE:
        enqueue(
            "ledger.kontakt_abgleichen",
            payload,
            firma=verbindung.firma,
            eindeutig=f"kontakt:{verbindung.pk}:{ereignis.resource_id}",
        )
    elif typ == "article.changed":
        enqueue("ledger.artikel_abgleichen", payload, firma=verbindung.firma, eindeutig=f"artikel:{verbindung.pk}")
    elif typ == "token.revoked":
        enqueue("connectors.token_widerrufen", payload, firma=verbindung.firma, eindeutig=f"widerruf:{verbindung.pk}")


@csrf_exempt
@login_not_required
@require_POST
def lexware(request: HttpRequest, token: str) -> HttpResponse:
    if is_ratelimited(request, group="webhook", key=lambda _g, _r: token, rate="600/15m", increment=True):
        return HttpResponse(status=429)
    verbindung = Verbindung.objects.select_related("firma").filter(webhook_token=token).first()
    if verbindung is None or verbindung.status == Verbindung.Status.GETRENNT:
        return HttpResponseNotFound()
    body = request.body
    if not signatur_gueltig(body, request.headers.get("X-Lxo-Signature", "")):
        log.warning("Webhook mit ungültiger Signatur verworfen", extra={"verbindung_id": verbindung.pk})
        return HttpResponse(status=401)
    try:
        daten = json.loads(body)
        typ = str(daten["eventType"])
        resource_id = str(daten["resourceId"])
        zeit = str(daten.get("eventDate", ""))
    except (ValueError, KeyError, TypeError):
        return HttpResponse(status=400)
    if verbindung.organisation_id and str(daten.get("organizationId", "")) != verbindung.organisation_id:
        log.warning("Webhook für fremde Organisation verworfen", extra={"verbindung_id": verbindung.pk})
        return HttpResponse(status=401)
    try:
        with transaction.atomic():
            ereignis = WebhookEreignis.objects.create(
                verbindung=verbindung, event_typ=typ, resource_id=resource_id, event_zeit=zeit, rohdaten=daten
            )
    except IntegrityError:
        return HttpResponse(status=200)  # bereits empfangen: idempotent
    ereignis_einplanen(verbindung, ereignis)
    return HttpResponse(status=202)
