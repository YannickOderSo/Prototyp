"""Jobs der Anbindung: Webhooks registrieren, Widerruf des Schlüssels behandeln."""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from accounts.models import Mitgliedschaft, Rolle
from audit.services import protokolliere
from jobs.models import Job
from jobs.registry import job
from jobs.worker import JobAbbruch

from .base import AccountingConnector
from .jobs import mit_connector
from .models import Verbindung
from .services import trennen
from .webhooks import callback_url

log = logging.getLogger(__name__)


@job("connectors.webhooks_registrieren")
def _registrieren(j: Job) -> None:
    def arbeit(verbindung: Verbindung, connector: AccountingConnector) -> None:
        url = callback_url(verbindung)
        if not url.startswith("https://"):
            # Lexware ruft nur öffentlich erreichbare HTTPS-Adressen auf; lokal bleibt es beim Nachtabgleich
            log.warning("Webhooks nicht registriert: keine HTTPS-Basis-URL", extra={"verbindung_id": verbindung.pk})
            return
        if verbindung.webhook_ids:
            connector.delete_webhooks(verbindung.webhook_ids)
        ids = connector.register_webhooks(url)
        Verbindung.objects.filter(pk=verbindung.pk).update(webhook_ids=ids)
        protokolliere(
            verbindung.firma, "verbindung.webhooks_registriert", objekt=verbindung, daten={"anzahl": len(ids)}
        )

    mit_connector(j, arbeit)


@job("connectors.token_widerrufen")
def _widerrufen(j: Job) -> None:
    verbindung = Verbindung.objects.select_related("firma").filter(pk=j.payload.get("verbindung_id")).first()
    if verbindung is None:
        raise JobAbbruch("Verbindung fehlt")
    if verbindung.status == Verbindung.Status.GETRENNT:
        return
    verbindung.webhook_ids = []  # Lexware hat die Abos mit dem Schlüssel entfernt
    verbindung.save(update_fields=["webhook_ids"])
    trennen(verbindung, None, grund="Der API-Schlüssel wurde in Lexware widerrufen.")
    empfaenger = list(
        Mitgliedschaft.objects.filter(firma=verbindung.firma, rolle=Rolle.INHABER).values_list(
            "nutzer__email", flat=True
        )
    )
    if empfaenger:
        send_mail(
            subject="Lexware-Verbindung getrennt",
            message=(
                "Guten Tag,\n\nder API-Schlüssel für Lexware Office wurde widerrufen. Belegfluss kann keine "
                "offenen Posten mehr abgleichen und keine Mahnungen vorbereiten.\n\nBitte hinterlegen Sie einen "
                f"neuen Schlüssel: {settings.BASIS_URL}{reverse('connectors:lexware')}\n"
            ),
            from_email=None,
            recipient_list=empfaenger,
        )
