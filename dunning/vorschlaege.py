"""Täglicher Vorschlagslauf (D2, D3, D8): erzeugt Vorschläge, versendet nie.

Ein Beleg bekommt einen Vorschlag für Stufe s nur, wenn alle Bedingungen gelten
(Mahnlogik-und-Recht.md, „Wann wird überhaupt vorgeschlagen“):
1. offen oder überfällig und offener Betrag > 0 (Rechnung oder Abschlag),
2. Kontakt mit Kundentyp (sonst „Klärung nötig“, kein Vorschlag),
3. weder Beleg noch Kontakt pausiert,
4. für diese Stufe gibt es noch keinen Vorschlag (eindeutig auf Beleg und Stufe),
5. die vorige Stufe wurde versendet und liegt mindestens `abstand_tage` zurück
   (Stufe 1 setzt Stufe 0 voraus, außer Stufe 0 ist abgeschaltet),
6. Tage seit Fälligkeit erreichen die Schwelle der Stufe; ohne Fälligkeit zählt das Belegdatum,
7. ohne E-Mail-Adresse: Vorschlag mit „Postversand nötig“.

Der Lauf ist idempotent: ein zweiter Lauf am selben Tag erzeugt keine Duplikate. Bestehende, noch nicht
freigegebene Vorschläge werden neu berechnet; ist der Beleg nicht mehr offen, werden sie verworfen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from accounts.models import Firma
from audit.services import protokolliere
from ledger.models import Beleg, Kundentyp

from . import recht
from .models import Mahnplan, Mahnvorschlag
from .services import basiszinstabelle, mahnplan_fuer

HOECHSTE_STUFE = 2


@dataclass
class Kandidat:
    beleg: Beleg
    stufe: int
    betraege: recht.MahnBetraege
    tage_ueberfaellig: int
    versandart: str
    hinweise: list[str] = field(default_factory=list)


@dataclass
class Laufergebnis:
    neu: list[Mahnvorschlag] = field(default_factory=list)
    aktualisiert: int = 0
    verworfen: int = 0
    klaerung: list[Beleg] = field(default_factory=list)
    kandidaten: list[Kandidat] = field(default_factory=list)


def vorschlaege_von(beleg: Beleg) -> list[Mahnvorschlag]:
    return list(beleg.mahnvorschlaege.all())  # type: ignore[attr-defined]  # Rückrelation aus dunning


def pausiert(beleg: Beleg, heute: date) -> bool:
    pausen = [beleg.mahnpause_bis, beleg.kontakt.mahnpause_bis if beleg.kontakt else None]
    return any(p is not None and p >= heute for p in pausen)


def verzugshinweis(beleg: Beleg, plan: Mahnplan) -> bool:
    if beleg.verzugshinweis_enthalten is not None:
        return beleg.verzugshinweis_enthalten
    return plan.verzugshinweis_auf_rechnungen


def forderung(beleg: Beleg, plan: Mahnplan) -> recht.Forderung:
    kundentyp = beleg.kontakt.kundentyp if beleg.kontakt else Kundentyp.UNBEKANNT
    return recht.Forderung(beleg.belegdatum, beleg.faellig_am, kundentyp, verzugshinweis(beleg, plan))


def _versendet(vorschlaege: list[Mahnvorschlag], stufe: int) -> Mahnvorschlag | None:
    return next((v for v in vorschlaege if v.stufe == stufe and v.status == Mahnvorschlag.Status.VERSENDET), None)


def erinnerung_versendet_am(vorschlaege: list[Mahnvorschlag]) -> date | None:
    erinnerung = _versendet(vorschlaege, 0)
    if erinnerung is None or erinnerung.versendet_am is None:
        return None
    return timezone.localtime(erinnerung.versendet_am).date()


def betraege(
    beleg: Beleg, stufe: int, plan: Mahnplan, vorschlaege: list[Mahnvorschlag], stichtag: date
) -> recht.MahnBetraege:
    pauschale_bereits = any(
        v.pauschale > 0 and v.status == Mahnvorschlag.Status.VERSENDET and v.stufe < stufe for v in vorschlaege
    )
    return recht.berechne(
        stufe,
        forderung(beleg, plan),
        beleg.offen,
        stichtag,
        basiszinstabelle(),
        erinnerung_versendet_am=erinnerung_versendet_am(vorschlaege),
        zinsen_aktiv=plan.zinsen_aktiv,
        pauschale_aktiv=plan.pauschale_aktiv,
        pauschale_bereits_geltend_gemacht=pauschale_bereits,
    )


def naechste_stufe(beleg: Beleg, plan: Mahnplan, vorschlaege: list[Mahnvorschlag], heute: date) -> int | None:
    """Welche Stufe jetzt fällig ist (Bedingungen 4 bis 6), oder None."""
    bezug = beleg.faellig_am or beleg.belegdatum
    if bezug is None:
        return None
    tage = (heute - bezug).days
    vorhandene = {v.stufe for v in vorschlaege}
    erste = 0 if plan.erinnerung_aktiv else 1
    for stufe in range(erste, HOECHSTE_STUFE + 1):
        if stufe in vorhandene:
            continue
        if tage < plan.tage_fuer_stufe(stufe):
            return None
        if stufe > erste:
            vorige = _versendet(vorschlaege, stufe - 1)
            if vorige is None or vorige.versendet_am is None:
                return None
            if (heute - timezone.localtime(vorige.versendet_am).date()).days < plan.abstand_tage:
                return None
        return stufe
    return None


def offene_kandidaten(firma: Firma) -> QuerySet[Beleg]:
    return (
        Beleg.objects.fuer(firma)
        .filter(status__in=Beleg.OFFENE_STATUS, offen__gt=0, art__in=[Beleg.Art.RECHNUNG, Beleg.Art.ABSCHLAG])
        .select_related("kontakt")
        .prefetch_related("mahnvorschlaege")
    )


def klaerung_noetig(firma: Firma, heute: date) -> list[Beleg]:
    """Überfällige Posten, die mangels Kundentyp oder Kontakt nicht gemahnt werden (D3)."""
    plan = mahnplan_fuer(firma)
    schwelle = plan.tage_erinnerung if plan.erinnerung_aktiv else plan.tage_mahnung1
    ergebnis = []
    for beleg in offene_kandidaten(firma).filter(Q(kontakt__isnull=True) | Q(kontakt__kundentyp=Kundentyp.UNBEKANNT)):
        bezug = beleg.faellig_am or beleg.belegdatum
        if bezug is not None and (heute - bezug).days >= schwelle and not pausiert(beleg, heute):
            ergebnis.append(beleg)
    return ergebnis


def berechnen(firma: Firma, heute: date) -> Laufergebnis:
    """Ermittelt, was heute vorgeschlagen würde, ohne zu speichern (auch für den Probelauf im Onboarding)."""
    plan = mahnplan_fuer(firma)
    ergebnis = Laufergebnis(klaerung=klaerung_noetig(firma, heute))
    for beleg in offene_kandidaten(firma).exclude(kontakt__isnull=True).exclude(kontakt__kundentyp=Kundentyp.UNBEKANNT):
        if pausiert(beleg, heute):
            continue
        vorschlaege = vorschlaege_von(beleg)
        stufe = naechste_stufe(beleg, plan, vorschlaege, heute)
        if stufe is None:
            continue
        b = betraege(beleg, stufe, plan, vorschlaege, heute)
        assert beleg.kontakt is not None
        versandart = "email" if beleg.kontakt.email else "post"
        hinweise = list(b.hinweise)
        if versandart == "post":
            hinweise.append("Postversand nötig: Für diesen Kunden ist in Lexware keine E-Mail-Adresse hinterlegt.")
        bezug = beleg.faellig_am or beleg.belegdatum
        assert bezug is not None
        ergebnis.kandidaten.append(Kandidat(beleg, stufe, b, (heute - bezug).days, versandart, hinweise))
    return ergebnis


def _werte(k: Kandidat, heute: date) -> dict[str, object]:
    return {
        "faellig_seit_tagen": k.tage_ueberfaellig,
        "offen_betrag": k.betraege.offen,
        "zinsen": k.betraege.zinsen,
        "pauschale": k.betraege.pauschale,
        "gesamt": k.betraege.gesamt,
        "verzugsbeginn": k.betraege.verzugsbeginn,
        "zinsberechnung": [
            {
                "von": a.von.isoformat(),
                "bis": a.bis.isoformat(),
                "tage": a.tage,
                "basiszins": str(a.basiszins),
                "zinssatz": str(a.zinssatz),
                "jahrestage": a.jahrestage,
                "betrag": str(a.betrag),
            }
            for a in k.betraege.zinsergebnis.abschnitte
        ]
        if k.betraege.zinsen > 0
        else [],
        "hinweise": k.hinweise,
        "versandart": k.versandart,
        "berechnet_am": heute,
    }


def neu_berechnen(vorschlag: Mahnvorschlag, heute: date) -> None:
    """Beträge eines noch nicht versendeten Vorschlags auf den heutigen Stand bringen."""
    beleg = vorschlag.beleg
    plan = mahnplan_fuer(vorschlag.firma)
    andere = [v for v in vorschlaege_von(beleg) if v.pk != vorschlag.pk]
    b = betraege(beleg, vorschlag.stufe, plan, andere, heute)
    bezug = beleg.faellig_am or beleg.belegdatum
    versandart = "email" if beleg.kontakt and beleg.kontakt.email else "post"
    hinweise = list(b.hinweise)
    if versandart == "post":
        hinweise.append("Postversand nötig: Für diesen Kunden ist in Lexware keine E-Mail-Adresse hinterlegt.")
    k = Kandidat(beleg, vorschlag.stufe, b, (heute - bezug).days if bezug else 0, versandart, hinweise)
    for feld, wert in _werte(k, heute).items():
        setattr(vorschlag, feld, wert)
    vorschlag.save()


def _aufraeumen(firma: Firma, heute: date, ergebnis: Laufergebnis) -> None:
    """Offene Vorschläge pflegen: bezahlt → verwerfen, pausiert → zurückziehen, sonst neu berechnen."""
    for vorschlag in (
        Mahnvorschlag.objects.fuer(firma)
        .filter(status=Mahnvorschlag.Status.VORGESCHLAGEN)
        .select_related("beleg", "beleg__kontakt", "firma")
    ):
        beleg = vorschlag.beleg
        if not beleg.ist_offen:
            vorschlag.status = Mahnvorschlag.Status.VERWORFEN
            vorschlag.verworfen_grund = "Beleg ist nicht mehr offen (bezahlt oder storniert)."
            vorschlag.save(update_fields=["status", "verworfen_grund"])
            ergebnis.verworfen += 1
        elif pausiert(beleg, heute) or not beleg.kontakt or beleg.kontakt.kundentyp == Kundentyp.UNBEKANNT:
            protokolliere(firma, "mahnvorschlag.zurueckgezogen", objekt=beleg, daten={"stufe": vorschlag.stufe})
            vorschlag.delete()  # nie freigegeben, keine Außenwirkung; nach der Pause neu vorschlagen
            ergebnis.verworfen += 1
        elif vorschlag.berechnet_am != heute:
            neu_berechnen(vorschlag, heute)
            ergebnis.aktualisiert += 1


def vorschlagslauf(firma: Firma, heute: date | None = None) -> Laufergebnis:
    """Speichert die heutigen Vorschläge. Idempotent je Beleg und Stufe."""
    heute = heute or timezone.localdate()
    ergebnis = Laufergebnis()
    _aufraeumen(firma, heute, ergebnis)
    berechnet = berechnen(firma, heute)
    ergebnis.klaerung = berechnet.klaerung
    ergebnis.kandidaten = berechnet.kandidaten
    for k in berechnet.kandidaten:
        try:
            with transaction.atomic():
                vorschlag = Mahnvorschlag.objects.create(firma=firma, beleg=k.beleg, stufe=k.stufe, **_werte(k, heute))
        except IntegrityError:
            continue  # parallel bereits angelegt
        ergebnis.neu.append(vorschlag)
    if ergebnis.neu:
        protokolliere(
            firma, "mahnlauf.vorschlaege_erzeugt", daten={"anzahl": len(ergebnis.neu), "datum": heute.isoformat()}
        )
    return ergebnis
