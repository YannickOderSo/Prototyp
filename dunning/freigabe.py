"""Freigabe durch Inhaber oder Freigeber (ADR-004, D6). Nur eingeloggte Nutzer mit 2FA erreichen diese Funktionen."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from jobs.models import Job
from jobs.queue import enqueue
from ledger.models import Kundentyp

from .models import Mahnvorschlag
from .vorschlaege import pausiert


@dataclass
class FreigabeErgebnis:
    freigegeben: list[Mahnvorschlag] = field(default_factory=list)
    abgelehnt: list[tuple[Mahnvorschlag, str]] = field(default_factory=list)


def versand_einplanen(vorschlag: Mahnvorschlag) -> Job:
    return enqueue(
        "dunning.versenden",
        {"vorschlag_id": vorschlag.pk},
        firma=vorschlag.firma,
        eindeutig=f"versand:{vorschlag.pk}",
        max_versuche=5,
    )


def _hinderungsgrund(vorschlag: Mahnvorschlag) -> str | None:
    beleg = vorschlag.beleg
    if vorschlag.status != Mahnvorschlag.Status.VORGESCHLAGEN:
        return "ist nicht mehr zur Freigabe vorgesehen"
    if not beleg.ist_offen:
        return "ist nicht mehr offen"
    if beleg.kontakt is None or beleg.kontakt.kundentyp == Kundentyp.UNBEKANNT:
        return "hat keinen Kundentyp"
    if pausiert(beleg, timezone.localdate()):
        return "ist pausiert"
    return None


def freigeben(firma: Firma, nutzer: Nutzer, ids: Iterable[int]) -> FreigabeErgebnis:
    """Gibt die Vorschläge der Firma frei und plant den Versand. Fremde IDs werden ignoriert (A4)."""
    ergebnis = FreigabeErgebnis()
    with transaction.atomic():
        for vorschlag in (
            Mahnvorschlag.objects.fuer(firma)
            .select_for_update(of=("self",))
            .filter(pk__in=list(ids))
            .select_related("beleg", "beleg__kontakt")
            .order_by("pk")
        ):
            grund = _hinderungsgrund(vorschlag)
            if grund:
                ergebnis.abgelehnt.append((vorschlag, grund))
                continue
            vorschlag.status = Mahnvorschlag.Status.FREIGEGEBEN
            vorschlag.freigegeben_von = nutzer
            vorschlag.freigegeben_am = timezone.now()
            vorschlag.fehler = ""
            vorschlag.save(update_fields=["status", "freigegeben_von", "freigegeben_am", "fehler"])
            protokolliere(
                firma,
                "mahnung.freigegeben",
                nutzer=nutzer,
                objekt=vorschlag,
                daten={"stufe": vorschlag.stufe, "beleg": vorschlag.beleg.nummer, "gesamt": str(vorschlag.gesamt)},
            )
            versand_einplanen(vorschlag)  # gleiche Transaktion: Job und Freigabe entstehen gemeinsam oder gar nicht
            ergebnis.freigegeben.append(vorschlag)
    return ergebnis


def verwerfen(vorschlag: Mahnvorschlag, nutzer: Nutzer, grund: str) -> None:
    if vorschlag.status not in (Mahnvorschlag.Status.VORGESCHLAGEN, Mahnvorschlag.Status.FEHLER):
        raise ValueError("Dieser Vorschlag kann nicht mehr verworfen werden.")
    vorschlag.status = Mahnvorschlag.Status.VERWORFEN
    vorschlag.verworfen_grund = grund[:300]
    vorschlag.save(update_fields=["status", "verworfen_grund"])
    protokolliere(vorschlag.firma, "mahnung.verworfen", nutzer=nutzer, objekt=vorschlag, daten={"grund": grund[:300]})


def neuversuch(vorschlag: Mahnvorschlag, nutzer: Nutzer) -> None:
    if vorschlag.status != Mahnvorschlag.Status.FEHLER:
        raise ValueError("Nur fehlgeschlagene Versände können erneut versucht werden.")
    vorschlag.status = Mahnvorschlag.Status.FREIGEGEBEN
    vorschlag.fehler = ""
    vorschlag.save(update_fields=["status", "fehler"])
    protokolliere(vorschlag.firma, "mahnung.neuversuch", nutzer=nutzer, objekt=vorschlag)
    versand_einplanen(vorschlag)


def als_post_versendet(vorschlag: Mahnvorschlag, nutzer: Nutzer) -> None:
    if vorschlag.status != Mahnvorschlag.Status.POST_BEREIT:
        raise ValueError("Der Vorschlag ist nicht für den Postversand vorbereitet.")
    with transaction.atomic():
        vorschlag.status = Mahnvorschlag.Status.VERSENDET
        vorschlag.versendet_am = timezone.now()
        vorschlag.save(update_fields=["status", "versendet_am"])
        beleg = vorschlag.beleg
        beleg.mahnstufe = max(beleg.mahnstufe, vorschlag.stufe + 1)
        beleg.save(update_fields=["mahnstufe"])
        protokolliere(vorschlag.firma, "mahnung.per_post_versendet", nutzer=nutzer, objekt=vorschlag)
