"""E-Mail-Versand von Erinnerungen und Mahnungen (ADR-006, D7, M2-06).

Standard: Plattform-SMTP (EU-Anbieter, Einstellungen EMAIL_*), Absender „Name der Firma <Plattformadresse>“,
Reply-To der Firma. Optional: eigenes SMTP der Firma mit eigener Absenderadresse.
Zustellfehler: sofortige Ablehnung durch den SMTP-Server wird direkt erfasst; spätere Bounces meldet der
Anbieter per Webhook (`zustellung_webhook`), soweit er das unterstützt. Formate: das eigene, generische Format und
das Ereignis-Format von Mailjet (einzeln oder gruppiert als Liste, ADR-012 Vorschlag).
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


def verbindung_fuer(firma: Firma, zugang: SmtpZugang | None = None) -> BaseEmailBackend:
    zugang = zugang or eigenes_smtp(firma)
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
        "Testmail aus Belegfluss",
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
    zugang = eigenes_smtp(firma)
    kopfzeilen = {"Message-ID": message_id, "Auto-Submitted": "auto-generated"}
    if zugang is None and settings.MAILVERSAND_ANBIETER == "mailjet":
        # Mailjet meldet Ereignisse ohne die Message-ID; die CustomID kommt im Ereignis als "CustomID" zurück
        kopfzeilen["X-MJ-CustomID"] = message_id.strip("<>")
    nachricht = EmailMessage(
        subject=mail.betreff,
        body=mail.text,
        from_email=mail.absender,
        to=[mail.empfaenger],
        bcc=[mail.bcc] if mail.bcc else None,
        reply_to=[mail.reply_to] if mail.reply_to else None,
        headers=kopfzeilen,
        connection=verbindung_fuer(firma, zugang),
    )
    if anhang is not None:
        nachricht.attach(mail.anhang_name, anhang, "application/pdf")
    try:
        nachricht.send(fail_silently=False)
    except smtplib.SMTPRecipientsRefused as fehler:
        raise Zustellfehler("Der Mailserver hat die Empfängeradresse abgelehnt.") from fehler
    return message_id


ZUSTELLFEHLER_EREIGNISSE = {"bounce", "hard_bounce", "soft_bounce", "dropped", "complaint", "rejected"}
MAX_EREIGNISSE = 500


class _UngueltigesFormat(ValueError):
    pass


def _mailjet(e: dict[str, object]) -> tuple[str, str, str] | None:
    """Ein Mailjet-Ereignis (Event API) → (Message-ID, Ereignis, Grund). Nur Zustellprobleme, sonst None.

    bounce → hard_bounce/soft_bounce (Feld hard_bounce), blocked → rejected (Mailjet hat nicht versendet),
    spam → complaint. sent, open, click und unsub sind keine Zustellfehler."""
    art = str(e.get("event", "")).lower()
    if art == "bounce":
        ereignis = "hard_bounce" if e.get("hard_bounce") is True else "soft_bounce"
    elif art == "blocked":
        ereignis = "rejected"
    elif art == "spam":
        ereignis = "complaint"
    else:
        return None
    custom = str(e.get("CustomID") or "").strip()
    if not custom:
        return None  # ohne X-MJ-CustomID nicht zuordenbar (z. B. Mail über eigenes SMTP oder Testversand)
    teile = [e.get("error_related_to"), e.get("error"), e.get("comment") or e.get("source")]
    return custom, ereignis, " / ".join(str(t) for t in teile if t)


def _ereignisse(daten: object) -> list[tuple[str, str, str]]:
    """Zustellmeldungen aus dem generischen Format oder dem Mailjet-Format (einzeln oder als Liste)."""
    if isinstance(daten, list):
        if len(daten) > MAX_EREIGNISSE:
            raise _UngueltigesFormat
        return [m for e in daten if isinstance(e, dict) and (m := _mailjet(e)) is not None]
    if not isinstance(daten, dict):
        raise _UngueltigesFormat
    if "event" in daten:
        m = _mailjet(daten)
        return [m] if m else []
    if "message_id" not in daten:
        raise _UngueltigesFormat
    ereignis = str(daten.get("ereignis", "")).lower()
    if ereignis not in ZUSTELLFEHLER_EREIGNISSE:
        return []
    return [(str(daten["message_id"]).strip(), ereignis, str(daten.get("grund", "")))]


def _zustellfehler_vermerken(message_id: str, ereignis: str, grund: str) -> None:
    from .models import Angebotserinnerung

    if not message_id.startswith("<"):
        message_id = f"<{message_id}>"
    text = f"{ereignis}: {grund[:500]}"
    for versand in Versand.objects.filter(message_id=message_id).select_related("firma"):
        versand.zustellfehler = text
        versand.zustellfehler_am = timezone.now()
        versand.save(update_fields=["zustellfehler", "zustellfehler_am"])
        protokolliere(versand.firma, "mahnung.zustellfehler", objekt=versand, daten={"ereignis": ereignis})
    for erinnerung in Angebotserinnerung.objects.filter(message_id=message_id).select_related("firma"):
        # sichtbar unter „Angebots-Erinnerung fehlgeschlagen“; keine zweite Erinnerung (eindeutig je Angebot)
        erinnerung.status = Angebotserinnerung.Status.FEHLER
        erinnerung.fehler = f"Nicht zugestellt ({text})"[:2000]
        erinnerung.save(update_fields=["status", "fehler"])
        protokolliere(erinnerung.firma, "angebot.zustellfehler", objekt=erinnerung, daten={"ereignis": ereignis})


@csrf_exempt
@login_not_required
@require_POST
def zustellung_webhook(request: HttpRequest, token: str) -> HttpResponse:
    """Empfänger für Zustellmeldungen des SMTP-Anbieters.

    Formate: generisch `{"message_id": "<…>", "ereignis": "bounce", "grund": "…"}` oder das Mailjet-Ereignis
    (`event`, `CustomID`, `hard_bounce`, `error_related_to`, `error`, …), einzeln oder gruppiert als Liste.
    Mailjet signiert nicht; geschützt wird über das geheime Token im Pfad (HTTPS). Erfolgreich verarbeitete Meldungen
    werden mit 200 bestätigt, denn Mailjet wiederholt jede andere Antwort 24 Stunden lang alle 30 Sekunden.
    """
    erwartet = settings.ZUSTELLUNG_WEBHOOK_TOKEN
    if not erwartet or not constant_time_compare(token, erwartet):
        return HttpResponse(status=404)
    if is_ratelimited(request, group="zustellung", key=lambda _g, _r: "alle", rate="600/15m", increment=True):
        return HttpResponse(status=429)
    try:
        meldungen = _ereignisse(json.loads(request.body))
    except (ValueError, TypeError):
        return HttpResponse(status=400)
    for message_id, ereignis, grund in meldungen:
        _zustellfehler_vermerken(message_id, ereignis, grund)
    return HttpResponse("ok", status=200, content_type="text/plain")
