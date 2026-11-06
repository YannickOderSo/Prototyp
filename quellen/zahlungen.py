"""K6–K8: Zahlungseingänge aus Kontoauszügen offenen Posten ohne Lexware zuordnen.

- Vorschläge macht eine Regel, keine KI: Rechnungsnummer im Verwendungszweck, sonst Betrag und Name, sonst nur Betrag.
- Der Zahlstatus ändert sich erst, wenn Inhaber oder Freigeber bestätigt. Bestätigen, andere Rechnung wählen und
  Ignorieren werden protokolliert.
- Posten aus Lexware sind ausgenommen: deren Zahlstatus kommt aus Lexware (ADR-003).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, QuerySet
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from ledger.models import Beleg

from . import bank
from .models import Kontoauszug, Zahlung

VERALTET_NACH_TAGEN = 2


class ZahlungFehler(ValueError):
    pass


def offene_posten(firma: Firma) -> QuerySet[Beleg]:
    return (
        Beleg.objects.fuer(firma)
        .exclude(quelle=Beleg.Quelle.LEXWARE)
        .filter(status__in=Beleg.OFFENE_STATUS, art__in=[Beleg.Art.RECHNUNG, Beleg.Art.ABSCHLAG], offen__gt=0)
    )


# ------------------------------------------------------------------ Hochladen


def einlesen(firma: Firma, dateiname: str, daten: bytes, nutzer: Nutzer | None) -> Kontoauszug:
    """Liest den Auszug, legt neue Gutschriften an und schlägt Rechnungen vor. Wirft bank.AuszugFehler."""
    auszug = bank.lesen(dateiname, daten)
    eintrag = Kontoauszug.objects.create(
        firma=firma,
        dateiname=(dateiname or "kontoauszug")[:200],
        format=auszug.format,
        konto=auszug.konto,
        von=auszug.von,
        bis=auszug.bis,
        gutschriften=len(auszug.umsaetze),
        hochgeladen_von=nutzer,
    )
    neu: list[Zahlung] = []
    for u in auszug.umsaetze:
        try:
            with transaction.atomic():
                zahlung = Zahlung.objects.create(
                    firma=firma,
                    kontoauszug=eintrag,
                    schluessel=u.schluessel,
                    buchungsdatum=u.buchungsdatum,
                    betrag=u.betrag,
                    waehrung=u.waehrung,
                    zahler=u.zahler,
                    zahler_konto=u.zahler_konto,
                    verwendungszweck=u.verwendungszweck,
                )
        except IntegrityError:
            eintrag.doppelt += 1
            continue
        neu.append(zahlung)
    eintrag.neu = len(neu)
    eintrag.save(update_fields=["neu", "doppelt"])
    posten = list(offene_posten(firma).select_related("kontakt"))
    for zahlung in neu:
        _vorschlag_setzen(zahlung, posten)
    protokolliere(
        firma,
        "kontoauszug.hochgeladen",
        nutzer=nutzer,
        objekt=eintrag,
        daten={
            "format": eintrag.format,
            "bis": eintrag.bis.isoformat() if eintrag.bis else "",
            "gutschriften": eintrag.gutschriften,
            "neu": eintrag.neu,
            "doppelt": eintrag.doppelt,
            "abbuchungen_verworfen": auszug.abbuchungen,
        },
    )
    return eintrag


# ------------------------------------------------------------------ Vorschlag (Regel, keine KI)


@dataclass
class Vorschlag:
    beleg: Beleg | None
    grund: str


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", text.upper())


def nummer_im_text(nummer: str, text: str) -> bool:
    """Rechnungsnummer im Verwendungszweck, auch mit anderen Trennzeichen („RE 2026/117“ für „RE-2026-117“)."""
    nummer = nummer.strip()
    if not nummer or not text:
        return False
    if re.search(rf"(?<![0-9A-Za-z]){re.escape(nummer)}(?![0-9])", text, re.IGNORECASE):
        return True
    kurz, flach = _alnum(nummer), _alnum(text)
    if len(kurz) < 4 or not any(z.isdigit() for z in kurz):
        return False
    for treffer in re.finditer(re.escape(kurz), flach):
        davor = flach[treffer.start() - 1] if treffer.start() else ""
        danach = flach[treffer.end()] if treffer.end() < len(flach) else ""
        if not (davor.isdigit() and kurz[0].isdigit()) and not danach.isdigit():
            return True
    # Nur die Ziffern („2026/0500“ für „RE-2026-0500“), wenn es genug sind, um nicht zufällig zu passen
    ziffern = re.sub(r"\D", "", nummer)
    if len(ziffern) >= 6:
        for treffer in re.finditer(ziffern, flach):
            davor = flach[treffer.start() - 1] if treffer.start() else ""
            danach = flach[treffer.end()] if treffer.end() < len(flach) else ""
            if not davor.isdigit() and not danach.isdigit():
                return True
    return False


def _woerter(text: str) -> set[str]:
    allgemein = {"gmbh", "mbh", "und", "ohg", "gbr", "inh", "inhaber", "co.", "kg", "herr", "frau", "familie"}
    return {w for w in re.findall(r"[a-zäöüß0-9]{4,}", (text or "").lower()) if w not in allgemein}


def _name_passt(beleg: Beleg, zahler: str) -> bool:
    name = beleg.kontakt.name if beleg.kontakt else beleg.kontakt_name
    return bool(_woerter(name) & _woerter(zahler))


def vorschlagen(zahlung: Zahlung, posten: list[Beleg]) -> Vorschlag:
    if zahlung.waehrung != "EUR":
        return Vorschlag(None, "Zahlung nicht in Euro.")
    mit_nummer = [b for b in posten if b.nummer and nummer_im_text(b.nummer, zahlung.verwendungszweck)]
    if len(mit_nummer) > 1:
        summe = sum((b.offen for b in mit_nummer), Decimal("0.00"))
        nummern = ", ".join(b.nummer for b in mit_nummer)
        return Vorschlag(
            None,
            f"Sammelzahlung für mehrere Rechnungen ({nummern}, zusammen {summe} € offen). Bitte einer Rechnung "
            "zuordnen und die übrigen am Posten unter „Zahlung eintragen“ erfassen.",
        )
    if len(mit_nummer) == 1:
        b = mit_nummer[0]
        if zahlung.betrag == b.offen:
            return Vorschlag(b, "Rechnungsnummer und Betrag passen.")
        if zahlung.betrag < b.offen:
            return Vorschlag(b, f"Rechnungsnummer passt; Teilzahlung, danach noch {b.offen - zahlung.betrag} € offen.")
        return Vorschlag(b, f"Rechnungsnummer passt; {zahlung.betrag - b.offen} € mehr gezahlt als offen.")
    gleicher_betrag = [b for b in posten if b.offen == zahlung.betrag]
    mit_name = [b for b in gleicher_betrag if _name_passt(b, zahlung.zahler)]
    if len(mit_name) == 1:
        return Vorschlag(mit_name[0], "Betrag und Name passen; keine Rechnungsnummer im Verwendungszweck.")
    if len(gleicher_betrag) == 1:
        return Vorschlag(gleicher_betrag[0], "Nur der Betrag passt. Bitte genau prüfen.")
    if len(gleicher_betrag) > 1:
        return Vorschlag(None, f"{len(gleicher_betrag)} offene Rechnungen haben diesen Betrag. Bitte auswählen.")
    return Vorschlag(None, "Keine passende offene Rechnung gefunden.")


def _vorschlag_setzen(zahlung: Zahlung, posten: list[Beleg]) -> None:
    v = vorschlagen(zahlung, posten)
    grund = v.grund
    gleich = (
        Zahlung.objects.fuer(zahlung.firma)
        .filter(buchungsdatum=zahlung.buchungsdatum, betrag=zahlung.betrag)
        .exclude(pk=zahlung.pk)
        .exclude(kontoauszug=zahlung.kontoauszug)
        .exists()
    )
    if gleich:
        grund = "Gleicher Betrag am selben Tag schon aus einem anderen Kontoauszug, vielleicht doppelt. " + grund
    zahlung.vorschlag, zahlung.vorschlag_grund = v.beleg, grund[:300]
    zahlung.save(update_fields=["vorschlag", "vorschlag_grund"])


def neu_vorschlagen(firma: Firma) -> int:
    """Nach neuen Rechnungskopien: offene Zahlungen ohne Vorschlag noch einmal prüfen."""
    posten = list(offene_posten(firma).select_related("kontakt"))
    anzahl = 0
    for zahlung in Zahlung.objects.fuer(firma).filter(status=Zahlung.Status.NEU, vorschlag__isnull=True):
        _vorschlag_setzen(zahlung, posten)
        anzahl += zahlung.vorschlag_id is not None
    return anzahl


# ------------------------------------------------------------------ Entscheidung durch Menschen


def bestaetigen(zahlung: Zahlung, beleg: Beleg, nutzer: Nutzer) -> Zahlung:
    """K7: Zahlung einem Posten zuordnen. Mindert den offenen Betrag; bei 0 ist der Posten bezahlt."""
    with transaction.atomic():
        zahlung = Zahlung.objects.select_for_update().get(pk=zahlung.pk, firma=zahlung.firma)
        beleg = Beleg.objects.select_for_update().get(pk=beleg.pk, firma=zahlung.firma)
        if zahlung.status != Zahlung.Status.NEU:
            raise ZahlungFehler("Diese Zahlung ist schon erledigt.")
        if not beleg.lokal:
            raise ZahlungFehler("Der Zahlstatus von Lexware-Rechnungen kommt aus Lexware.")
        if beleg.status not in Beleg.OFFENE_STATUS or beleg.offen <= 0:
            raise ZahlungFehler(f"Rechnung {beleg.nummer} ist nicht mehr offen.")
        alt = beleg.offen
        beleg.offen = max(alt - zahlung.betrag, Decimal("0.00"))
        if beleg.offen == 0:
            beleg.status, beleg.bezahlt_am = Beleg.Status.BEZAHLT, zahlung.buchungsdatum
        beleg.save(update_fields=["offen", "status", "bezahlt_am"])
        zahlung.status, zahlung.beleg = Zahlung.Status.ZUGEORDNET, beleg
        zahlung.erledigt_von, zahlung.erledigt_am = nutzer, timezone.now()
        zahlung.save(update_fields=["status", "beleg", "erledigt_von", "erledigt_am"])
    protokolliere(
        zahlung.firma,
        "zahlung.zugeordnet",
        nutzer=nutzer,
        objekt=beleg,
        daten={
            "zahlung": zahlung.pk,
            "betrag": str(zahlung.betrag),
            "buchungsdatum": zahlung.buchungsdatum.isoformat(),
            "offen_alt": str(alt),
            "offen_neu": str(beleg.offen),
            "ueberzahlt": str(max(zahlung.betrag - alt, Decimal("0.00"))),
            "wie_vorgeschlagen": zahlung.vorschlag_id == beleg.pk,
        },
    )
    return zahlung


def ignorieren(zahlung: Zahlung, nutzer: Nutzer) -> None:
    with transaction.atomic():
        gesperrt = Zahlung.objects.select_for_update().get(pk=zahlung.pk, firma=zahlung.firma)
        if gesperrt.status != Zahlung.Status.NEU:
            raise ZahlungFehler("Diese Zahlung ist schon erledigt.")
        gesperrt.status = Zahlung.Status.IGNORIERT
        gesperrt.erledigt_von, gesperrt.erledigt_am = nutzer, timezone.now()
        gesperrt.save(update_fields=["status", "erledigt_von", "erledigt_am"])
    protokolliere(
        zahlung.firma,
        "zahlung.ignoriert",
        nutzer=nutzer,
        objekt=gesperrt,
        daten={"betrag": str(gesperrt.betrag), "buchungsdatum": gesperrt.buchungsdatum.isoformat()},
    )


# ------------------------------------------------------------------ Stand für die Mahnfreigabe (K8)


@dataclass
class Stand:
    bis: date | None
    veraltet: bool
    offene_zahlungen: int

    @property
    def text(self) -> str:
        if self.bis is None:
            return "Noch kein Kontoauszug hochgeladen. Ob inzwischen bezahlt wurde, weiß Belegfluss nicht."
        tage = (timezone.localdate() - self.bis).days
        alter = "heute" if tage <= 0 else ("gestern" if tage == 1 else f"vor {tage} Tagen")
        satz = f"Letzter Kontoauszug mit Stand {self.bis:%d.%m.%Y} ({alter})."
        if self.veraltet:
            satz += " Bitte vor der Freigabe einen aktuellen Kontoauszug hochladen."
        if self.offene_zahlungen:
            satz += f" {self.offene_zahlungen} Zahlung(en) noch nicht zugeordnet."
        return satz


def stand(firma: Firma) -> Stand:
    bis = Kontoauszug.objects.fuer(firma).aggregate(m=Max("bis"))["m"]
    veraltet = bis is None or bis < timezone.localdate() - timedelta(days=VERALTET_NACH_TAGEN)
    offen = Zahlung.objects.fuer(firma).filter(status=Zahlung.Status.NEU).count()
    return Stand(bis, veraltet, offen)


def offene_zahlung_fuer(beleg: Beleg) -> Zahlung | None:
    """Frische-Check vor dem Versand: Liegt eine nicht zugeordnete Zahlung mit Vorschlag für diesen Posten vor?"""
    return (
        Zahlung.objects.fuer(beleg.firma)
        .filter(status=Zahlung.Status.NEU, vorschlag=beleg)
        .order_by("-buchungsdatum")
        .first()
    )
