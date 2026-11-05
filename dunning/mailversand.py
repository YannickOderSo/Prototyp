"""E-Mail-Versand von Erinnerungen und Mahnungen (ADR-006, D7).

Standard: Plattform-SMTP (EU-Anbieter, Einstellungen EMAIL_*), Absendername der Firma, Reply-To der Firma.
"""

from __future__ import annotations

import smtplib
from email.utils import make_msgid

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.core.mail.backends.base import BaseEmailBackend

from accounts.models import Firma

from .mail import MailInhalt


class Zustellfehler(Exception):
    """Der Empfänger wurde vom Mailserver abgelehnt (dauerhaft, kein Neuversuch)."""


def verbindung_fuer(firma: Firma) -> BaseEmailBackend:
    return get_connection(fail_silently=False)


def message_id_domain() -> str:
    absender = settings.DEFAULT_FROM_EMAIL
    return absender.split("@", 1)[1] if "@" in absender else "cockpit.local"


def senden(firma: Firma, mail: MailInhalt, anhang: bytes) -> str:
    """Sendet die Mail mit PDF-Anhang. Gibt die Message-ID zurück."""
    if not mail.empfaenger:
        raise Zustellfehler("Keine E-Mail-Adresse beim Kunden hinterlegt")
    message_id = make_msgid(domain=message_id_domain())
    nachricht = EmailMessage(
        subject=mail.betreff,
        body=mail.text,
        from_email=mail.absender,
        to=[mail.empfaenger],
        bcc=[mail.bcc] if mail.bcc else None,
        reply_to=[mail.reply_to] if mail.reply_to else None,
        headers={"Message-ID": message_id, "Auto-Submitted": "auto-generated"},
        connection=verbindung_fuer(firma),
    )
    nachricht.attach(mail.anhang_name, anhang, "application/pdf")
    try:
        nachricht.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as fehler:
        raise Zustellfehler("Der Mailserver hat die Empfängeradresse abgelehnt.") from fehler
    return message_id
