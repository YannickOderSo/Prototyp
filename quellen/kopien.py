"""Rechnungskopien übernehmen (K1–K5): aus der Kopie einer Ausgangsrechnung wird ein offener Posten im Cockpit.

Regeln:
- Der Posten lebt nur in Belegfluss (Quelle „Rechnungskopie“), nie in einem Bestandstool (ADR-001, ADR-011).
- Nur Eindeutiges wird automatisch übernommen. Andere Währung, fehlende Fälligkeit, Korrekturrechnung, fremder
  Verkäufer, Gutschrift ohne passende Rechnung und jedes PDF ohne E-Rechnung gehen in die Prüfung durch einen Menschen.
- Den Kundentyp setzt immer der Nutzer (K4); ein neuer Kunde wird bis dahin nicht gemahnt.
- Die Datei selbst wird nicht gespeichert, nur die gelesenen Felder.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from ledger.models import Beleg, Kontakt

from . import erechnung
from .models import Rechnungskopie

log = logging.getLogger(__name__)

MAX_DATEI_BYTES = 25 * 1024 * 1024
FELDER = ("nummer", "belegdatum", "faellig_am", "kaeufer_name", "kaeufer_email", "brutto", "zahlbetrag")


class KopieFehler(ValueError):
    pass


# ------------------------------------------------------------------ Einlesen


def einlesen(
    firma: Firma,
    dateiname: str,
    daten: bytes,
    *,
    weg: str = Rechnungskopie.Weg.UPLOAD,
    nutzer: Nutzer | None = None,
    message_id: str = "",
) -> Rechnungskopie:
    """Liest eine Datei und übernimmt sie, wenn alles eindeutig ist; sonst bleibt sie zur Prüfung liegen."""
    dateiname = (dateiname or "rechnung")[:200]
    kopie = Rechnungskopie(firma=firma, weg=weg, dateiname=dateiname, message_id=message_id[:300], erstellt_von=nutzer)
    if len(daten) > MAX_DATEI_BYTES:
        kopie.status, kopie.grund = Rechnungskopie.Status.ABGELEHNT, "Die Datei ist größer als 25 MB."
        kopie.save()
        return _protokoll(kopie, nutzer)
    try:
        rechnung = erechnung.lesen(dateiname, daten)
    except erechnung.KeineERechnung as fehler:
        if daten[:5] != b"%PDF-":
            kopie.status, kopie.grund = Rechnungskopie.Status.ABGELEHNT, str(fehler)
            kopie.save()
            return _protokoll(kopie, nutzer)
        _pdf_ohne_erechnung(kopie, dateiname, daten)
        return _protokoll(kopie, nutzer)
    except erechnung.ERechnungFehler as fehler:
        kopie.status, kopie.grund = Rechnungskopie.Status.ABGELEHNT, str(fehler)
        kopie.save()
        return _protokoll(kopie, nutzer)
    kopie.format = rechnung.format
    kopie.daten = _werte_aus(rechnung)
    kopie.save()
    gruende = pruefgruende(firma, kopie.daten)
    if gruende:
        kopie.grund = " ".join(gruende)
        kopie.save(update_fields=["grund"])
    else:
        kopie = uebernehmen(kopie, kopie.daten, nutzer=None)
    return _protokoll(kopie, nutzer)


def _pdf_ohne_erechnung(kopie: Rechnungskopie, dateiname: str, daten: bytes) -> None:
    """K5: PDF ohne strukturierte Daten. Die KI liest vor (Job), ein Mensch bestätigt."""
    from capture.aufbereitung import pdf

    quelle = pdf(dateiname, daten)
    kopie.format = "pdf"
    kopie.text = quelle.text
    kopie.daten = {"art": "rechnung", "waehrung": "EUR"}
    if quelle.text:
        kopie.grund = "Keine E-Rechnung: Die Werte hat die KI aus dem PDF gelesen. Bitte prüfen und bestätigen."
    else:
        kopie.grund = " ".join(quelle.hinweise) or "Das PDF enthält keinen lesbaren Text. Bitte Werte eintragen."
    kopie.save()
    if quelle.text:
        from jobs.queue import enqueue

        enqueue("quellen.ki_lesen", {"kopie_id": kopie.pk}, firma=kopie.firma, eindeutig=f"kopie-ki:{kopie.pk}")


def _protokoll(kopie: Rechnungskopie, nutzer: Nutzer | None) -> Rechnungskopie:
    protokolliere(
        kopie.firma,
        "rechnungskopie.eingegangen",
        nutzer=nutzer,
        objekt=kopie,
        daten={"weg": kopie.weg, "format": kopie.format, "status": kopie.status},
    )
    return kopie


def _werte_aus(r: erechnung.ERechnung) -> dict[str, Any]:
    """Flache, bearbeitbare Werte aus der E-Rechnung (dieselben Schlüssel wie im Prüfformular)."""
    return {
        "nummer": r.nummer,
        "art": r.art,
        "art_code": r.art_code,
        "belegdatum": r.belegdatum.isoformat() if r.belegdatum else "",
        "faellig_am": r.faellig_am.isoformat() if r.faellig_am else "",
        "faelligkeit_aus": r.faelligkeit_aus,
        "waehrung": r.waehrung,
        "verkaeufer": r.verkaeufer,
        "kaeufer_name": r.kaeufer.name,
        "kaeufer_email": r.kaeufer.email,
        "kaeufer_ustid": r.kaeufer.ustid,
        "kaeufer_anschrift": r.kaeufer.anschrift,
        "brutto": str(r.brutto),
        "zahlbetrag": str(r.zahlbetrag),
        "bezug": r.bezug,
        "zahlungsbedingungen": r.zahlungsbedingungen,
    }


# ------------------------------------------------------------------ Prüfen


def _woerter(text: str) -> set[str]:
    allgemein = {"gmbh", "mbh", "und", "der", "die", "das", "ohg", "gbr", "e.k.", "inh", "inhaber", "co.", "kg"}
    return {w for w in re.findall(r"[a-zäöüß0-9]{4,}", text.lower()) if w not in allgemein}


def gleiche_firma(firmenname: str, verkaeufer: str) -> bool:
    """Grob: mindestens ein bedeutsames Wort gemeinsam (z. B. „Muster“). Leerer Verkäufer zählt nicht als fremd."""
    if not verkaeufer.strip():
        return True
    return bool(_woerter(firmenname) & _woerter(verkaeufer))


def _datum(wert: object) -> date | None:
    try:
        return date.fromisoformat(str(wert)[:10]) if wert else None
    except ValueError:
        return None


def _betrag(wert: object) -> Decimal | None:
    try:
        return Decimal(str(wert)).quantize(Decimal("0.01")) if str(wert).strip() else None
    except (InvalidOperation, ValueError):
        return None


def pruefgruende(firma: Firma, werte: dict[str, Any]) -> list[str]:
    gruende = []
    art = werte.get("art", "rechnung")
    if (werte.get("waehrung") or "EUR").upper() != "EUR":
        gruende.append("Die Rechnung ist nicht in Euro.")
    if not werte.get("nummer"):
        gruende.append("Die Rechnungsnummer fehlt.")
    if art == "korrektur":
        gruende.append("Rechnungskorrektur: Bitte prüfen, welche Rechnung sie ersetzt.")
    if art in ("rechnung", "abschlag") and not _datum(werte.get("faellig_am")):
        gruende.append("Die Fälligkeit steht nicht eindeutig in der Rechnung.")
    if not _datum(werte.get("belegdatum")):
        gruende.append("Das Rechnungsdatum fehlt.")
    if not gleiche_firma(firma.name, str(werte.get("verkaeufer") or "")):
        gruende.append(f"Verkäufer „{werte.get('verkaeufer')}“ ist nicht Ihre Firma. Ist das eine Eingangsrechnung?")
    if art == "gutschrift" and not _rechnung_zur_gutschrift(firma, str(werte.get("bezug") or "")):
        gruende.append("Zu dieser Gutschrift gibt es keine passende offene Rechnung im Cockpit.")
    if _betrag(werte.get("zahlbetrag")) is None:
        gruende.append("Der Betrag fehlt.")
    return gruende


def _rechnung_zur_gutschrift(firma: Firma, nummer: str) -> Beleg | None:
    if not nummer:
        return None
    return (
        Beleg.objects.fuer(firma)
        .filter(nummer=nummer, art__in=[Beleg.Art.RECHNUNG, Beleg.Art.ABSCHLAG])
        .exclude(quelle=Beleg.Quelle.LEXWARE)
        .first()
    )


# ------------------------------------------------------------------ Übernehmen


def _doppelt(firma: Firma, kopie: Rechnungskopie, nummer: str) -> Beleg | bool | None:
    """Gleiche Nummer schon übernommen oder als Rechnung im Cockpit: keine zweite Übernahme (K3)."""
    frueher = (
        Rechnungskopie.objects.fuer(firma)
        .filter(status=Rechnungskopie.Status.ANGELEGT, daten__nummer=nummer)
        .exclude(pk=kopie.pk)
        .first()
    )
    if frueher is not None:
        return frueher.beleg or True
    return Beleg.objects.fuer(firma).filter(nummer=nummer, art__in=[Beleg.Art.RECHNUNG, Beleg.Art.ABSCHLAG]).first()


def uebernehmen(kopie: Rechnungskopie, werte: dict[str, Any], nutzer: Nutzer | None) -> Rechnungskopie:
    """Legt den Posten an (oder bucht die Gutschrift). `nutzer` gesetzt = von einem Menschen bestätigt."""
    firma = kopie.firma
    nummer = str(werte.get("nummer") or "").strip()[:50]
    art = str(werte.get("art") or "rechnung")
    with transaction.atomic():
        kopie = Rechnungskopie.objects.select_for_update().get(pk=kopie.pk)
        if kopie.status in (Rechnungskopie.Status.ANGELEGT, Rechnungskopie.Status.DOPPELT):
            return kopie
        kopie.daten = {**kopie.daten, **werte}
        if art != "gutschrift":
            vorhanden = _doppelt(firma, kopie, nummer)
            if vorhanden:
                kopie.status = Rechnungskopie.Status.DOPPELT
                kopie.beleg = vorhanden if isinstance(vorhanden, Beleg) else None
                kopie.grund = f"Rechnung {nummer} ist schon im Cockpit."
                _abschliessen(kopie, nutzer)
                return kopie
        if art == "gutschrift":
            beleg = _gutschrift(kopie, werte, nutzer)
        else:
            beleg = _posten(kopie, werte, nutzer)
        kopie.status, kopie.beleg, kopie.grund = Rechnungskopie.Status.ANGELEGT, beleg, ""
        _abschliessen(kopie, nutzer)
    return kopie


def _abschliessen(kopie: Rechnungskopie, nutzer: Nutzer | None) -> None:
    kopie.text = ""  # PDF-Text wird nach der Entscheidung nicht mehr gebraucht
    if nutzer is not None:
        kopie.geprueft_von, kopie.geprueft_am = nutzer, timezone.now()
    kopie.save()


def _posten(kopie: Rechnungskopie, werte: dict[str, Any], nutzer: Nutzer | None) -> Beleg:
    firma = kopie.firma
    heute = timezone.localdate()
    nummer = str(werte.get("nummer") or "").strip()[:50]
    faellig = _datum(werte.get("faellig_am"))
    brutto = _betrag(werte.get("brutto")) or _betrag(werte.get("zahlbetrag")) or Decimal("0.00")
    offen = max(_betrag(werte.get("zahlbetrag")) or Decimal("0.00"), Decimal("0.00"))
    if offen <= 0:
        status = Beleg.Status.BEZAHLT
    elif faellig and faellig < heute:
        status = Beleg.Status.UEBERFAELLIG
    else:
        status = Beleg.Status.OFFEN
    kontakt = kunde_finden_oder_anlegen(firma, werte, nutzer)
    if werte.get("art") == "korrektur" and werte.get("bezug"):
        ersetzt = _rechnung_zur_gutschrift(firma, str(werte["bezug"]))
        if ersetzt is not None and ersetzt.status in Beleg.OFFENE_STATUS:
            Beleg.objects.filter(pk=ersetzt.pk).update(status=Beleg.Status.STORNIERT, offen=Decimal("0.00"))
            protokolliere(firma, "rechnungskopie.korrektur_ersetzt", nutzer=nutzer, objekt=ersetzt)
    beleg = Beleg.objects.create(
        firma=firma,
        extern_id=f"kopie-{uuid.uuid4().hex}",
        art=Beleg.Art.ABSCHLAG if werte.get("art") == "abschlag" else Beleg.Art.RECHNUNG,
        nummer=nummer,
        belegdatum=_datum(werte.get("belegdatum")),
        faellig_am=faellig,
        kontakt=kontakt,
        kontakt_name=kontakt.name,
        brutto=brutto,
        offen=offen,
        status=status,
        bezahlt_am=heute if status == Beleg.Status.BEZAHLT else None,
        quelle=Beleg.Quelle.KOPIE,
    )
    protokolliere(
        firma,
        "rechnungskopie.posten_angelegt",
        nutzer=nutzer,
        objekt=beleg,
        daten={"nummer": nummer, "offen": str(offen), "bestaetigt": nutzer is not None},
    )
    return beleg


def _gutschrift(kopie: Rechnungskopie, werte: dict[str, Any], nutzer: Nutzer | None) -> Beleg:
    firma = kopie.firma
    rechnung = _rechnung_zur_gutschrift(firma, str(werte.get("bezug") or ""))
    if rechnung is None:
        raise KopieFehler("Zu dieser Gutschrift gibt es keine passende Rechnung im Cockpit.")
    betrag = _betrag(werte.get("zahlbetrag")) or Decimal("0.00")
    alt = rechnung.offen
    rechnung.offen = max(rechnung.offen - betrag, Decimal("0.00"))
    if rechnung.offen == 0:
        rechnung.status = Beleg.Status.BEZAHLT if rechnung.bezahlt_am else Beleg.Status.STORNIERT
    rechnung.save(update_fields=["offen", "status"])
    protokolliere(
        firma,
        "rechnungskopie.gutschrift",
        nutzer=nutzer,
        objekt=rechnung,
        daten={"gutschrift": str(werte.get("nummer") or ""), "alt": str(alt), "neu": str(rechnung.offen)},
    )
    return rechnung


def kunde_finden_oder_anlegen(firma: Firma, werte: dict[str, Any], nutzer: Nutzer | None) -> Kontakt:
    """K4: über E-Mail, sonst eindeutigen Namen; sonst neuer Kunde im Cockpit mit Kundentyp „unbekannt“."""
    name = str(werte.get("kaeufer_name") or "").strip()[:250] or "Kunde ohne Namen"
    email = str(werte.get("kaeufer_email") or "").strip().lower()[:254]
    kontakte = Kontakt.objects.fuer(firma).filter(archiviert=False)
    if email:
        treffer = kontakte.filter(email__iexact=email).first()
        if treffer is not None:
            return treffer
    gleiche = list(kontakte.filter(name__iexact=name)[:2])
    if len(gleiche) == 1:
        kontakt = gleiche[0]
        if email and not kontakt.email:
            kontakt.email = email
            kontakt.save(update_fields=["email"])
        return kontakt
    kontakt = Kontakt.objects.create(
        firma=firma,
        extern_id=f"lokal-{uuid.uuid4().hex[:20]}",
        name=name,
        email=email,
        adresse=str(werte.get("kaeufer_anschrift") or "")[:1000],
        ist_unternehmen_extern=True if werte.get("kaeufer_ustid") else None,
    )
    protokolliere(firma, "kontakt.aus_rechnungskopie_angelegt", nutzer=nutzer, objekt=kontakt)
    return kontakt


def verwerfen(kopie: Rechnungskopie, nutzer: Nutzer) -> None:
    if kopie.status != Rechnungskopie.Status.PRUEFUNG:
        raise KopieFehler("Nur Kopien in der Prüfung lassen sich verwerfen.")
    kopie.status = Rechnungskopie.Status.VERWORFEN
    _abschliessen(kopie, nutzer)
    protokolliere(kopie.firma, "rechnungskopie.verworfen", nutzer=nutzer, objekt=kopie)
