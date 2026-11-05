"""Dateien annehmen: Typ nach Inhalt (nicht nach Endung), Größenlimits, Ablage außerhalb des Webroots.

Grenzen (E1, Sicherheit): je Datei 25 MB, je Erfassung höchstens 10 Dateien und 50 MB.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Datei, Erfassung, neuer_pfad

MAX_DATEI_BYTES = 25 * 1024 * 1024
MAX_DATEIEN = 10
MAX_GESAMT_BYTES = 50 * 1024 * 1024
MAX_AUFNAHME_SEKUNDEN = 5 * 60


class DateiAbgelehnt(ValueError):
    pass


@dataclass(frozen=True)
class Typ:
    art: str
    mime: str


_FTYP_AUDIO = (b"M4A ", b"M4B ", b"mp42", b"isom", b"mp41", b"dash", b"iso5", b"iso6")
_FTYP_HEIC = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1")


def _ist_text(daten: bytes) -> str | None:
    if b"\x00" in daten[:8192]:
        return None
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            return daten[:65536].decode(kodierung)
        except UnicodeDecodeError:
            continue
    return None


def typ_erkennen(daten: bytes, name: str) -> Typ:
    """Bestimmt den Dateityp anhand der ersten Bytes. Unbekanntes wird abgelehnt."""
    kopf = daten[:64]
    if kopf.startswith(b"%PDF-"):
        return Typ("pdf", "application/pdf")
    if kopf.startswith(b"\xff\xd8\xff"):
        return Typ("bild", "image/jpeg")
    if kopf.startswith(b"\x89PNG\r\n\x1a\n"):
        return Typ("bild", "image/png")
    if kopf[4:8] == b"ftyp":
        marke = kopf[8:12]
        if marke in _FTYP_HEIC:
            return Typ("bild", "image/heic")
        if marke in _FTYP_AUDIO:
            return Typ("audio", "audio/mp4")
    if kopf.startswith(b"\x1a\x45\xdf\xa3"):
        return Typ("audio", "audio/webm")
    if kopf.startswith(b"OggS"):
        return Typ("audio", "audio/ogg")
    if kopf.startswith(b"RIFF") and kopf[8:12] == b"WAVE":
        return Typ("audio", "audio/wav")
    if kopf.startswith(b"ID3") or kopf[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return Typ("audio", "audio/mpeg")
    if kopf.startswith((b"MZ", b"\x7fELF", b"#!", b"PK\x03\x04")):
        raise DateiAbgelehnt("Programme und Archive werden nicht angenommen.")
    text = _ist_text(daten)
    if text is not None:
        endung = Path(name).suffix.lower()
        anfang = text.lstrip()[:2000].lower()
        if endung == ".eml" or ("from:" in anfang and ("subject:" in anfang or "betreff:" in anfang)):
            return Typ("mail", "message/rfc822")
        if endung == ".csv":
            return Typ("csv", "text/csv")
        if "<script" in anfang or "<html" in anfang:
            raise DateiAbgelehnt("HTML-Dateien werden nicht angenommen.")
        return Typ("text", "text/plain")
    raise DateiAbgelehnt(
        "Dieser Dateityp wird nicht unterstützt. Erlaubt sind Audio, Fotos (JPG, PNG, HEIC), PDF, CSV, TXT und EML."
    )


def _sicherer_name(name: str) -> str:
    basis = os.path.basename(name.replace("\\", "/")) or "datei"
    return "".join(ch for ch in basis if ch.isalnum() or ch in "._- ")[:200] or "datei"


def ablage() -> Path:
    pfad = Path(settings.DATEIABLAGE)
    pfad.mkdir(parents=True, exist_ok=True)
    return pfad


def speichern(erfassung: Erfassung, name: str, daten: bytes) -> Datei:
    if len(daten) == 0:
        raise DateiAbgelehnt(f"„{name}“ ist leer.")
    if len(daten) > MAX_DATEI_BYTES:
        raise DateiAbgelehnt(f"„{name}“ ist größer als 25 MB.")
    vorhandene = list(Datei.objects.filter(erfassung=erfassung))
    if len(vorhandene) >= MAX_DATEIEN:
        raise DateiAbgelehnt("Höchstens 10 Dateien je Erfassung.")
    if sum(d.groesse for d in vorhandene) + len(daten) > MAX_GESAMT_BYTES:
        raise DateiAbgelehnt("Höchstens 50 MB je Erfassung.")
    typ = typ_erkennen(daten, name)
    relativ = neuer_pfad(erfassung.firma_id)
    ziel = ablage() / relativ
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(daten)
    os.chmod(ziel, 0o600)
    return Datei.objects.create(
        firma_id=erfassung.firma_id,
        erfassung=erfassung,
        name=_sicherer_name(name),
        art=typ.art,
        mime=typ.mime,
        groesse=len(daten),
        sha256=hashlib.sha256(daten).hexdigest(),
        pfad=relativ,
    )


def lesen(datei: Datei) -> bytes:
    if datei.geloescht_am is not None:
        raise FileNotFoundError("Datei wurde gelöscht")
    return (ablage() / datei.pfad).read_bytes()


def loeschen(datei: Datei) -> None:
    """Löscht den Inhalt; der Datensatz bleibt als Nachweis (Name, Größe, Hash) erhalten."""
    pfad = ablage() / datei.pfad
    if pfad.exists():
        pfad.unlink()
    if datei.geloescht_am is None:
        datei.geloescht_am = timezone.now()
        datei.save(update_fields=["geloescht_am"])
