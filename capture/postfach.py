"""Belegpostfach (E2): Mails an belege+<token>@domain werden zu Erfassungen.

Sicherheit (Sicherheit-Datenschutz-Betrieb.md):
- Absender nur aus der Whitelist der Firma UND bestandene DKIM- oder SPF-Prüfung mit Alignment zur From-Domain.
- Geprüft wird ausschließlich der `Authentication-Results`-Kopf des eigenen Mailservers (authserv-id aus der
  Einstellung). Kopfzeilen, die der Absender selbst mitschickt, zählen nicht.
- Höchstens 10 Anhänge, je 25 MB, zusammen 50 MB.
- IMAP mit Timeout; jede Mail wird für sich verarbeitet, ein Fehler hält die anderen nicht auf.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import imaplib
import logging
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Any, Protocol

from django.conf import settings
from django.db import IntegrityError, transaction

from audit.services import protokolliere

from .dateien import MAX_DATEI_BYTES, MAX_DATEIEN, MAX_GESAMT_BYTES, DateiAbgelehnt
from .models import Belegpostfach, PostfachEingang
from .services import anlegen

log = logging.getLogger(__name__)

IMAP_TIMEOUT = 30
MAX_JE_ABRUF = 50


def adresse(postfach: Belegpostfach) -> str:
    lokal, _, domain = settings.BELEGPOSTFACH_ADRESSE.partition("@")
    return f"{lokal}+{postfach.token}@{domain}" if domain else ""


def _domain(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].lower().strip(">").strip() if "@" in adresse else ""


def ausgerichtet(domain: str, from_domain: str) -> bool:
    """Relaxed Alignment: gleiche Domain oder Subdomain derselben Organisation (vereinfacht)."""
    if not domain or not from_domain:
        return False
    return domain == from_domain or domain.endswith("." + from_domain) or from_domain.endswith("." + domain)


@dataclass(frozen=True)
class Pruefung:
    ok: bool
    grund: str = ""


def authentifizierung(nachricht: EmailMessage, authserv_id: str) -> Pruefung:
    """DKIM pass (header.d) oder SPF pass (smtp.mailfrom), jeweils ausgerichtet auf die From-Domain."""
    if not authserv_id:
        return Pruefung(False, "Mailserver-Kennung (authserv-id) nicht konfiguriert")
    from_domain = _domain(parseaddr(str(nachricht.get("From", "")))[1])
    for kopf in nachricht.get_all("Authentication-Results") or []:
        text = " ".join(str(kopf).split())
        kennung, _, rest = text.partition(";")
        woerter = kennung.split()
        if not woerter or woerter[0].lower() != authserv_id.lower():
            continue  # fremder oder vom Absender mitgeschickter Kopf
        for teil in rest.split(";"):
            teil = teil.strip()
            dkim = re.match(r"dkim=pass\b.*?\bheader\.(?:d|i)=@?([\w.-]+)", teil, re.IGNORECASE)
            if dkim and ausgerichtet(dkim.group(1).lower(), from_domain):
                return Pruefung(True)
            spf = re.match(r"spf=pass\b.*?\bsmtp\.mailfrom=(?:[^@\s]*@)?([\w.-]+)", teil, re.IGNORECASE)
            if spf and ausgerichtet(spf.group(1).lower(), from_domain):
                return Pruefung(True)
        return Pruefung(False, "DKIM und SPF nicht bestanden oder nicht passend zur Absenderdomain")
    return Pruefung(False, "Kein Prüfergebnis des eigenen Mailservers")


class HatAbsender(Protocol):
    absender: Any


def absender_erlaubt(postfach: HatAbsender, absender: str) -> bool:
    absender = absender.lower().strip()
    for eintrag in postfach.absender:
        eintrag = str(eintrag).lower().strip()
        if not eintrag:
            continue
        if eintrag.startswith("@") and absender.endswith(eintrag):
            return True
        if eintrag == absender:
            return True
    return False


def _token(nachricht: EmailMessage) -> str | None:
    lokal, _, domain = settings.BELEGPOSTFACH_ADRESSE.lower().partition("@")
    if not domain:
        return None
    kandidaten = []
    for kopf in ("Delivered-To", "X-Original-To", "To", "Cc"):
        kandidaten += [a for _, a in getaddresses([str(v) for v in nachricht.get_all(kopf) or []])]
    for kandidat in kandidaten:
        treffer = re.fullmatch(rf"{re.escape(lokal)}\+([a-z0-9]+)@{re.escape(domain)}", kandidat.lower().strip())
        if treffer:
            return treffer.group(1)
    return None


def _nur_text(nachricht: EmailMessage) -> bytes:
    """Kopf und Text ohne Anhänge als kleine .eml (Quelle „aus Mail“)."""
    koerper = nachricht.get_body(preferencelist=("plain", "html"))
    ohne = EmailMessage()
    for kopf in ("From", "To", "Date", "Subject"):
        if nachricht.get(kopf):
            ohne[kopf] = str(nachricht.get(kopf))
    ohne.set_content(str(koerper.get_content()) if koerper is not None else "")
    return bytes(ohne)


def _anhaenge(nachricht: EmailMessage) -> list[tuple[str, bytes]]:
    anhaenge = []
    for teil in nachricht.iter_attachments():
        nutzlast = teil.get_payload(decode=True)
        if isinstance(nutzlast, bytes):
            anhaenge.append((teil.get_filename() or "anhang", nutzlast))
    if len(anhaenge) > MAX_DATEIEN - 1:
        raise DateiAbgelehnt("Zu viele Anhänge (höchstens 10).")
    if any(len(d) > MAX_DATEI_BYTES for _, d in anhaenge):
        raise DateiAbgelehnt("Ein Anhang ist größer als 25 MB.")
    if sum(len(d) for _, d in anhaenge) > MAX_GESAMT_BYTES:
        raise DateiAbgelehnt("Die Anhänge sind zusammen größer als 50 MB.")
    return anhaenge


def verarbeiten(roh: bytes) -> PostfachEingang:
    """Verarbeitet eine Mail vollständig für sich. Gibt das Ergebnis zurück (angenommen/abgelehnt/doppelt)."""
    nachricht = email.message_from_bytes(roh, policy=email.policy.default)
    assert isinstance(nachricht, EmailMessage)
    message_id = str(nachricht.get("Message-ID") or "").strip()[:300] or f"ohne-id-{hashlib.sha256(roh).hexdigest()}"
    if PostfachEingang.objects.filter(message_id=message_id).exists():
        return PostfachEingang(message_id=message_id, ergebnis="doppelt")
    token = _token(nachricht)
    absender = parseaddr(str(nachricht.get("From", "")))[1]
    if token and token.startswith("r"):
        # ADR-011 Stufe 3: Kopie einer eigenen Ausgangsrechnung (eigene Adresse je Firma, Präfix „r“)
        from quellen.postfach import kopie_verarbeiten

        return kopie_verarbeiten(nachricht, token, message_id, absender)
    postfach = Belegpostfach.objects.select_related("firma").filter(token=token, aktiv=True).first() if token else None

    def ablehnen(grund: str) -> PostfachEingang:
        eingang = PostfachEingang.objects.create(
            message_id=message_id, firma=postfach.firma if postfach else None, ergebnis="abgelehnt", grund=grund[:300]
        )
        if postfach is not None:
            protokolliere(
                postfach.firma,
                "belegpostfach.abgelehnt",
                objekt=postfach,
                daten={"grund": grund, "domain": _domain(absender)},
            )
        log.warning(
            "Belegpostfach: Mail verworfen", extra={"grund": grund, "firma_id": postfach.firma_id if postfach else None}
        )
        return eingang

    if postfach is None:
        return ablehnen("Unbekannte oder inaktive Belegadresse")
    if not absender_erlaubt(postfach, absender):
        return ablehnen("Absender nicht in der Whitelist")
    pruefung = authentifizierung(nachricht, settings.BELEGPOSTFACH_AUTHSERV_ID)
    if not pruefung.ok:
        return ablehnen(pruefung.grund)
    try:
        dateien = [("mail.eml", _nur_text(nachricht)), *_anhaenge(nachricht)]
        with transaction.atomic():
            erfassung = anlegen(postfach.firma, None, "mail", dateien, absender=absender)
            eingang = PostfachEingang.objects.create(
                message_id=message_id, firma=postfach.firma, ergebnis="angenommen", erfassung=erfassung
            )
    except DateiAbgelehnt as fehler:
        return ablehnen(str(fehler))
    except IntegrityError:
        return PostfachEingang(message_id=message_id, ergebnis="doppelt")
    return eingang


def imap_verbindung() -> imaplib.IMAP4:
    return imaplib.IMAP4_SSL(settings.BELEGPOSTFACH_IMAP_HOST, settings.BELEGPOSTFACH_IMAP_PORT, timeout=IMAP_TIMEOUT)


def abrufen() -> list[PostfachEingang]:
    """Holt ungelesene Mails (höchstens 50 je Lauf) und markiert sie nach der Verarbeitung als gelesen."""
    if not (settings.BELEGPOSTFACH_IMAP_HOST and settings.BELEGPOSTFACH_ADRESSE):
        return []
    ergebnisse = []
    imap = imap_verbindung()
    try:
        imap.login(settings.BELEGPOSTFACH_IMAP_BENUTZER, settings.BELEGPOSTFACH_IMAP_PASSWORT)
        imap.select(settings.BELEGPOSTFACH_IMAP_ORDNER)
        _, daten = imap.search(None, "UNSEEN")
        nummern = [n.decode() if isinstance(n, bytes) else str(n) for n in (daten[0] or b"").split()[:MAX_JE_ABRUF]]
        for nummer in nummern:
            try:
                _, teile = imap.fetch(nummer, "(RFC822)")
                roh = next(t[1] for t in teile if isinstance(t, tuple))
                ergebnisse.append(verarbeiten(roh))
            except Exception:
                log.exception("Belegpostfach: Mail konnte nicht verarbeitet werden")
            finally:
                imap.store(nummer, "+FLAGS", "\\Seen")
    finally:
        try:
            imap.logout()
        except Exception:
            log.warning("Belegpostfach: Abmelden fehlgeschlagen")
    return ergebnisse
