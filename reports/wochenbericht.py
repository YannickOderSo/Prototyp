"""Wöchentlicher Liquiditätsbericht (F1): eingegangen, überfällig, gemahnt, Prognose.

Wird montags als Abschnitt der Sammelfreigabe-Mail versendet (dunning/sammelmail.py) und ist im Cockpit
unter „Berichte“ einsehbar.

„Eingegangen“ ist die Summe der Rechnungen, die laut Lexware in den letzten 7 Tagen vollständig bezahlt
wurden (Bruttobetrag). Teilzahlungen auf weiterhin offene Rechnungen sind darin nicht enthalten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from accounts.models import Firma
from dunning.mail import euro
from dunning.models import Mahnvorschlag
from ledger import auswertung
from ledger.models import Beleg
from ledger.services import als_posten, offene_belege, verzug_je_kontakt

NULL = Decimal("0.00")


@dataclass
class Wochenbericht:
    von: date
    bis: date
    eingegangen_summe: Decimal
    eingegangen_anzahl: int
    kennzahlen: auswertung.Kennzahlen
    gemahnt: list[tuple[str, int, Decimal]]
    prognose: auswertung.Prognose


def bericht(firma: Firma, heute: date | None = None) -> Wochenbericht:
    heute = heute or timezone.localdate()
    von = heute - timedelta(days=7)
    bezahlt = (
        Beleg.objects.fuer(firma)
        .filter(status=Beleg.Status.BEZAHLT, bezahlt_am__gte=von, bezahlt_am__lt=heute)
        .exclude(art=Beleg.Art.ANGEBOT)
    )
    summe = bezahlt.aggregate(s=Sum("brutto"), n=Count("id"))
    posten = als_posten(offene_belege(firma))
    gemahnt = []
    for stufe, label in Mahnvorschlag.Stufe.choices:
        versendet = (
            Mahnvorschlag.objects.fuer(firma)
            .filter(
                stufe=stufe,
                status=Mahnvorschlag.Status.VERSENDET,
                versendet_am__date__gte=von,
                versendet_am__date__lt=heute,
            )
            .aggregate(n=Count("id"), s=Sum("gesamt"))
        )
        gemahnt.append((label, int(versendet["n"] or 0), versendet["s"] or NULL))
    return Wochenbericht(
        von=von,
        bis=heute - timedelta(days=1),
        eingegangen_summe=summe["s"] or NULL,
        eingegangen_anzahl=int(summe["n"] or 0),
        kennzahlen=auswertung.kennzahlen(posten, heute),
        gemahnt=gemahnt,
        prognose=auswertung.prognose(posten, verzug_je_kontakt(firma, heute), heute),
    )


def als_text(b: Wochenbericht) -> str:
    rechnungen = "Rechnung" if b.eingegangen_anzahl == 1 else "Rechnungen"
    zeilen = [
        "",
        f"Wochenbericht {b.von:%d.%m.} bis {b.bis:%d.%m.%Y}",
        "-" * 40,
        f"Eingegangen: {euro(b.eingegangen_summe)} ({b.eingegangen_anzahl} {rechnungen} vollständig bezahlt)",
        f"Offen gesamt: {euro(b.kennzahlen.summe_offen)} ({b.kennzahlen.anzahl_offen} Posten)",
        f"Überfällig: {euro(b.kennzahlen.summe_ueberfaellig)} ({b.kennzahlen.anzahl_ueberfaellig} Posten)",
    ]
    for klasse in b.kennzahlen.klassen:
        if klasse.anzahl:
            zeilen.append(f"  {klasse.name} überfällig: {euro(klasse.summe)}")
    zeilen.append("Gemahnt in der letzten Woche:")
    for label, anzahl, summe in b.gemahnt:
        zeilen.append(f"  {label}: {anzahl}{f' ({euro(summe)})' if anzahl else ''}")
    zeilen.append("Erwarteter Geldeingang:")
    for woche in b.prognose.wochen:
        zeilen.append(f"  {woche.beginn:%d.%m.}–{woche.ende:%d.%m.}: {euro(woche.summe)}")
    if b.prognose.anzahl_unsicher:
        zeilen.append(f"  dazu überfällig mit unsicherem Termin: {euro(b.prognose.unsicher)}")
    return "\n".join(zeilen) + "\n"


def abschnitt(firma: Firma, jetzt: datetime) -> str:
    """Abschnitt für die Sammelfreigabe-Mail (dunning.sammelmail.ABSCHNITTE)."""
    return als_text(bericht(firma, timezone.localdate(jetzt)))
