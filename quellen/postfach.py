"""K1: Mails an die Kopie-Adresse (…+r<token>@…) – gleiche Sicherheitsprüfungen wie das Belegpostfach.

Nur Absender aus der Liste der Firma und bestandene DKIM- oder SPF-Prüfung des eigenen Mailservers. Aus jedem
PDF- oder XML-Anhang wird eine Rechnungskopie; der Mailtext wird nicht gespeichert.
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

from django.conf import settings
from django.db import IntegrityError, transaction

from audit.services import protokolliere
from capture.dateien import DateiAbgelehnt
from capture.models import PostfachEingang
from capture.postfach import _anhaenge, _domain, absender_erlaubt, authentifizierung

from . import kopien
from .models import Kopieadresse, Rechnungskopie

log = logging.getLogger(__name__)


def kopie_verarbeiten(nachricht: EmailMessage, token: str, message_id: str, absender: str) -> PostfachEingang:
    adresse = Kopieadresse.objects.select_related("firma").filter(token=token, aktiv=True).first()

    def ablehnen(grund: str) -> PostfachEingang:
        eingang = PostfachEingang.objects.create(
            message_id=message_id, firma=adresse.firma if adresse else None, ergebnis="abgelehnt", grund=grund[:300]
        )
        if adresse is not None:
            protokolliere(
                adresse.firma,
                "rechnungskopie.abgelehnt",
                objekt=adresse,
                daten={"grund": grund, "domain": _domain(absender)},
            )
        log.warning("Kopie-Adresse: Mail verworfen", extra={"grund": grund})
        return eingang

    if adresse is None:
        return ablehnen("Unbekannte oder inaktive Kopie-Adresse")
    if not absender_erlaubt(adresse, absender):
        return ablehnen("Absender nicht in der Liste der Firma")
    pruefung = authentifizierung(nachricht, settings.BELEGPOSTFACH_AUTHSERV_ID)
    if not pruefung.ok:
        return ablehnen(pruefung.grund)
    try:
        dateien = [(n, d) for n, d in _anhaenge(nachricht) if n.lower().endswith((".pdf", ".xml"))]
    except DateiAbgelehnt as fehler:
        return ablehnen(str(fehler))
    if not dateien:
        return ablehnen("Keine Rechnungsdatei (PDF oder XML) im Anhang")
    try:
        with transaction.atomic():
            eingang = PostfachEingang.objects.create(message_id=message_id, firma=adresse.firma, ergebnis="kopie")
            for name, daten in dateien:
                kopien.einlesen(adresse.firma, name, daten, weg=Rechnungskopie.Weg.MAIL, message_id=message_id)
    except IntegrityError:
        return PostfachEingang(message_id=message_id, ergebnis="doppelt")
    return eingang
