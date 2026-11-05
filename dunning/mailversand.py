"""E-Mail-Versand von Erinnerungen und Mahnungen (ADR-006, D7, M2-06).

Standard: Plattform-SMTP (EU-Anbieter, Einstellungen EMAIL_*), Absender „Name der Firma <Plattformadresse>“,
Reply-To der Firma. Optional: eigenes SMTP der Firma mit eigener Absenderadresse.
Zustellfehler: sofortige Ablehnung durch den SMTP-Server wird direkt erfasst; spätere Bounces meldet der
Anbieter per Webhook (`zustellung_webhook`), soweit er das unterstützt.
"""

from __future__ import annotations

import json
import logging
import smtplib
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.mail import EmailMessage, get_connection
from django.core.mail.backends.base import BaseEmailBackend
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django_ratelimit.core import is_ratelimited

from accounts.models import Firma
from audit.services import protokolliere
from cockpit.krypto import entschluesseln

from .models import SmtpZugang, Versand

if TYPE_CHECKING:
    from .mail import MailInhalt

log = logging.getLogger(__name__)


class Zustellfehler(Exception):
    """Der Empfänger wurde vom Mailserver abgelehnt (dauerhaft, kein Neuversuch)."""


def eigenes_smtp(firma: Firma) -> SmtpZugang | None:
    return SmtpZugang.objects.fuer(firma).filter(aktiv=True).first()


def verbindung_fuer(firma: Firma) -> BaseEmailBackend:
    zugang = eigenes_smtp(firma)
    if zugang is None:
        return get_connection(fail_silently=False)
    return smtp_verbindung(zugang)


def smtp_verbindung(zugang: SmtpZugang) -> BaseEmailBackend:
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend",
        host=zugang.host,
        port=zugang.port,
        username=zugang.benutzer,
        password=entschluesseln(zugang.passwort_verschluesselt) if zugang.passwort_verschluesselt else "",
        use_tls=zugang.starttls and not zugang.ssl,
        use_ssl=zugang.ssl,
        timeout=30,
        fail_silently=False,
    )


def testmail(zugang: SmtpZugang, empfaenger: str) -> None:
    """Prüft einen (noch nicht aktiven) SMTP-Zugang mit einer Testmail. Wirft bei jedem Fehler."""
    EmailMessage(
        "Testmail aus dem Forderungs-Cockpit",
        "Diese Testmail bestätigt, dass Ihr SMTP-Zugang funktioniert.",
        from_email=zugang.absender_adresse,
        to=[empfaenger],
        connection=smtp_verbindung(zugang),
    ).send(fail_silently=False)


def absender_adresse(firma: Firma) -> str:
    zugang = eigenes_smtp(firma)
    return zugang.absender_adresse if zugang else settings.DEFAULT_FROM_EMAIL


def message_id_domain(adresse: str) -> str:
    return adresse.split("@", 1)[1] if "@" in adresse else "cockpit.local"


def senden(firma: Firma, mail: MailInhalt, anhang: bytes | None) -> str:
    """Sendet die Mail (mit PDF-Anhang, falls vorhanden). Gibt die Message-ID zurück."""
    from email.utils import make_msgid, parseaddr

    if not mail.empfaenger:
        raise Zustellfehler("Keine E-Mail-Adresse beim Kunden hinterlegt")
    message_id = make_msgid(domain=message_id_domain(parseaddr(mail.absender)[1]))
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
    if anhang is not None:
        nachricht.attach(mail.anhang_name, anhang, "application/pdf")
    try:
        nachricht.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as fehler:
        raise Zustellfehler("Der Mailserver hat die Empfängeradresse abgelehnt.") from fehler
    return message_id


ZUSTELLFEHLER_EREIGNISSE = {"bounce", "hard_bounce", "soft_bounce", "dropped", "complaint", "rejected"}


@csrf_exempt
@login_not_required
@require_POST
def zustellung_webhook(request: HttpRequest, token: str) -> HttpResponse:
    """Generischer Empfänger für Zustellmeldungen des SMTP-Anbieters.

    Erwartet JSON `{"message_id": "<…>", "ereignis": "bounce", "grund": "…"}`. Das konkrete Format hängt vom
    gewählten EU-Anbieter ab (offene Frage); ein kleiner Adapter übersetzt es in dieses Format.
    """
    erwartet = settings.ZUSTELLUNG_WEBHOOK_TOKEN
    if not erwartet or not constant_time_compare(token, erwartet):
        return HttpResponse(status=404)
    if is_ratelimited(request, group="zustellung", key=lambda _g, _r: "alle", rate="600/15m", increment=True):
        return HttpResponse(status=429)
    try:
        daten = json.loads(request.body)
        message_id = str(daten["message_id"]).strip()
        ereignis = str(daten.get("ereignis", "")).lower()
    except (ValueError, KeyError, TypeError):
        return HttpResponse(status=400)
    if ereignis not in ZUSTELLFEHLER_EREIGNISSE:
        return HttpResponse(status=204)
    if not message_id.startswith("<"):
        message_id = f"<{message_id}>"
    for versand in Versand.objects.filter(message_id=message_id).select_related("firma"):
        versand.zustellfehler = f"{ereignis}: {str(daten.get('grund', ''))[:500]}"
        versand.zustellfehler_am = timezone.now()
        versand.save(update_fields=["zustellfehler", "zustellfehler_am"])
        protokolliere(versand.firma, "mahnung.zustellfehler", objekt=versand, daten={"ereignis": ereignis})
    return HttpResponse(status=204)
