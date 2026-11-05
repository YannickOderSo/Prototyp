"""Datenbankzugriffe für das Cockpit. Jede Abfrage ist auf eine Firma beschränkt (A4)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Q, QuerySet

from accounts.models import Firma

from . import auswertung
from .models import Beleg, Kontakt, Kundentyp


def offene_belege(firma: Firma | None) -> QuerySet[Beleg]:
    return (
        Beleg.objects.fuer(firma)
        .filter(status__in=Beleg.OFFENE_STATUS, offen__gt=0)
        .exclude(art=Beleg.Art.ANGEBOT)
        .select_related("kontakt")
    )


def als_posten(belege: QuerySet[Beleg]) -> list[auswertung.Posten]:
    return [
        auswertung.Posten(offen=b.offen, faellig_am=b.faellig_am, belegdatum=b.belegdatum, kontakt_id=b.kontakt_id)
        for b in belege
    ]


def zahlungen(firma: Firma | None, kontakt: Kontakt | None = None) -> list[auswertung.Zahlung]:
    qs = Beleg.objects.fuer(firma).filter(status=Beleg.Status.BEZAHLT, bezahlt_am__isnull=False)
    if kontakt is not None:
        qs = qs.filter(kontakt=kontakt)
    return [
        auswertung.Zahlung(belegdatum=b.belegdatum, faellig_am=b.faellig_am, bezahlt_am=b.bezahlt_am)
        for b in qs.only("belegdatum", "faellig_am", "bezahlt_am")
        if b.bezahlt_am
    ]


def verzug_je_kontakt(firma: Firma | None, heute: date) -> dict[int, Decimal | None]:
    gruppen: dict[int, list[auswertung.Zahlung]] = defaultdict(list)
    qs = Beleg.objects.fuer(firma).filter(status=Beleg.Status.BEZAHLT, bezahlt_am__isnull=False, kontakt__isnull=False)
    for b in qs.only("kontakt_id", "belegdatum", "faellig_am", "bezahlt_am"):
        if b.kontakt_id is not None and b.bezahlt_am is not None:
            gruppen[b.kontakt_id].append(auswertung.Zahlung(b.belegdatum, b.faellig_am, b.bezahlt_am))
    return {kontakt_id: auswertung.verzug(liste, heute) for kontakt_id, liste in gruppen.items()}


@dataclass
class Cockpit:
    kennzahlen: auswertung.Kennzahlen
    prognose: auswertung.Prognose
    verzug_monate: list[auswertung.Monatswert]
    ohne_kundentyp: int
    dringend: list[Beleg]


def cockpit(firma: Firma | None, heute: date) -> Cockpit:
    belege = offene_belege(firma)
    posten = als_posten(belege)
    return Cockpit(
        kennzahlen=auswertung.kennzahlen(posten, heute),
        prognose=auswertung.prognose(posten, verzug_je_kontakt(firma, heute), heute),
        verzug_monate=auswertung.verzug_je_monat(zahlungen(firma), heute),
        ohne_kundentyp=kontakte_ohne_kundentyp(firma).count(),
        dringend=list(belege.filter(faellig_am__lt=heute).order_by("faellig_am")[:5]),
    )


def kontakte_ohne_kundentyp(firma: Firma | None) -> QuerySet[Kontakt]:
    """Kontakte mit offenen Posten, deren Kundentyp fehlt (Voraussetzung für das Mahnen, D3)."""
    return (
        Kontakt.objects.fuer(firma)
        .filter(kundentyp=Kundentyp.UNBEKANNT, belege__status__in=Beleg.OFFENE_STATUS, belege__offen__gt=0)
        .distinct()
        .order_by("name")
    )


SORTIERUNGEN = {
    "faellig": ("faellig_am", "id"),
    "-faellig": ("-faellig_am", "-id"),
    "betrag": ("offen", "id"),
    "-betrag": ("-offen", "-id"),
    "kunde": ("kontakt_name", "faellig_am"),
    "-kunde": ("-kontakt_name", "faellig_am"),
    "mahnstufe": ("mahnstufe", "faellig_am"),
    "-mahnstufe": ("-mahnstufe", "faellig_am"),
}


def posten_filtern(firma: Firma | None, filter: dict[str, object], heute: date) -> QuerySet[Beleg]:
    """C2: kombinierbare Filter nach Kunde, Fälligkeit, Betrag, Mahnstufe; Sortierung."""
    qs = offene_belege(firma)
    if filter.get("kunde"):
        text = str(filter["kunde"])
        qs = qs.filter(Q(kontakt_name__icontains=text) | Q(kontakt__name__icontains=text) | Q(nummer__icontains=text))
    if filter.get("kontakt"):
        qs = qs.filter(kontakt_id=int(str(filter["kontakt"])))
    faelligkeit = filter.get("faelligkeit")
    if faelligkeit == "ueberfaellig":
        qs = qs.filter(Q(faellig_am__lt=heute) | Q(faellig_am__isnull=True, belegdatum__lt=heute))
    elif faelligkeit == "nicht_faellig":
        qs = qs.filter(Q(faellig_am__gte=heute) | Q(faellig_am__isnull=True, belegdatum__gte=heute))
    if filter.get("faellig_von"):
        qs = qs.filter(faellig_am__gte=filter["faellig_von"])
    if filter.get("faellig_bis"):
        qs = qs.filter(faellig_am__lte=filter["faellig_bis"])
    if filter.get("betrag_min") is not None:
        qs = qs.filter(offen__gte=filter["betrag_min"])
    if filter.get("betrag_max") is not None:
        qs = qs.filter(offen__lte=filter["betrag_max"])
    if filter.get("mahnstufe") not in (None, ""):
        qs = qs.filter(mahnstufe=int(str(filter["mahnstufe"])))
    return qs.order_by(*SORTIERUNGEN.get(str(filter.get("sortierung") or "faellig"), SORTIERUNGEN["faellig"]))
