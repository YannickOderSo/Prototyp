"""Verbindung anlegen, prüfen, trennen. Schlüssel werden nur verschlüsselt gespeichert (B1)."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from cockpit.krypto import entschluesseln, verschluesseln

from .base import AccountingConnector
from .demo import DEMO_ORGANISATION
from .fehler import ConnectorFehler
from .lexware import LexwareConnector
from .models import Verbindung


def connector_fuer(verbindung: Verbindung) -> AccountingConnector:
    if verbindung.typ != Verbindung.Typ.LEXWARE:
        raise NotImplementedError("sevdesk folgt in M5")
    if settings.DEBUG and verbindung.organisation_id == DEMO_ORGANISATION:
        # Nur lokale Demo (manage.py demo_daten): keine Anfrage nach außen
        from .demo import DemoConnector

        return DemoConnector(verbindung.firma)
    return LexwareConnector(entschluesseln(verbindung.schluessel_verschluesselt), basis_url=settings.LEXWARE_BASIS_URL)


def aktive_verbindung(firma: Firma) -> Verbindung | None:
    return (
        Verbindung.objects.fuer(firma)
        .filter(status=Verbindung.Status.AKTIV)
        .exclude(schluessel_verschluesselt="")
        .first()
    )


def verbinden(firma: Firma, nutzer: Nutzer, schluessel: str) -> Verbindung:
    """Prüft den Schlüssel sofort mit einem Testaufruf und speichert ihn verschlüsselt.

    Wirft `ConnectorFehler`, wenn Lexware den Schlüssel ablehnt; dann wird nichts gespeichert.
    """
    schluessel = schluessel.strip()
    info = LexwareConnector(schluessel, basis_url=settings.LEXWARE_BASIS_URL).test()
    with transaction.atomic():
        verbindung, neu = Verbindung.objects.get_or_create(firma=firma, typ=Verbindung.Typ.LEXWARE)
        if not neu and verbindung.organisation_id and verbindung.organisation_id != info.organisation_id:
            raise ConnectorFehler(
                "Dieser Schlüssel gehört zu einem anderen Lexware-Konto. Bitte trennen Sie zuerst die alte Verbindung."
            )
        verbindung.schluessel_verschluesselt = verschluesseln(schluessel)
        verbindung.status = Verbindung.Status.AKTIV
        verbindung.firmenname_extern = info.firmenname
        verbindung.organisation_id = info.organisation_id
        verbindung.steuerart = info.steuerart
        verbindung.kleinunternehmer = info.kleinunternehmer
        verbindung.fehler = ""
        verbindung.getrennt_am = None
        verbindung.save()
        protokolliere(
            firma,
            "verbindung.angelegt" if neu else "verbindung.schluessel_erneuert",
            nutzer=nutzer,
            objekt=verbindung,
            daten={"typ": verbindung.typ, "organisation_id": info.organisation_id},
        )
    return verbindung


def trennen(verbindung: Verbindung, nutzer: Nutzer | None, grund: str = "vom Nutzer getrennt") -> None:
    """Trennt die Verbindung: Webhooks abmelden (soweit möglich), Schlüssel löschen, Status setzen."""
    if verbindung.aktiv and verbindung.webhook_ids:
        try:
            connector_fuer(verbindung).delete_webhooks(verbindung.webhook_ids)
        except ConnectorFehler:
            pass  # z. B. Schlüssel bereits widerrufen; Lexware entfernt Abos dann selbst
    verbindung.schluessel_verschluesselt = ""
    verbindung.webhook_ids = []
    verbindung.status = Verbindung.Status.GETRENNT
    verbindung.getrennt_am = timezone.now()
    verbindung.fehler = grund
    verbindung.save()
    protokolliere(verbindung.firma, "verbindung.getrennt", nutzer=nutzer, objekt=verbindung, daten={"grund": grund})
