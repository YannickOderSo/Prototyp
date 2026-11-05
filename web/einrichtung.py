"""Onboarding-Assistent (F6): Lexware verbinden → Kundentypen setzen → Mahnplan wählen → Probelauf ansehen."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from connectors.models import Verbindung
from dunning.models import Mahnplan
from dunning.services import mahnplan_fuer
from ledger.services import kontakte_ohne_kundentyp


@dataclass(frozen=True)
class Vorlage:
    """Vorlage für den Mahnplan (Tage nach Fälligkeit). Abstände jeweils mindestens 7 Tage."""

    titel: str
    text: str
    tage_erinnerung: int
    tage_mahnung1: int
    tage_mahnung2: int
    zinsen_aktiv: bool
    pauschale_aktiv: bool

    def werte(self) -> dict[str, int | bool]:
        return {
            "tage_erinnerung": self.tage_erinnerung,
            "tage_mahnung1": self.tage_mahnung1,
            "tage_mahnung2": self.tage_mahnung2,
            "zinsen_aktiv": self.zinsen_aktiv,
            "pauschale_aktiv": self.pauschale_aktiv,
        }


VORLAGEN = {
    "freundlich": Vorlage(
        "Freundlich",
        "Erinnerung nach 10, 1. Mahnung nach 28, 2. Mahnung nach 45 Tagen, ohne Zinsen und Pauschale",
        10,
        28,
        45,
        zinsen_aktiv=False,
        pauschale_aktiv=False,
    ),
    "standard": Vorlage(
        "Standard",
        "Erinnerung nach 7, 1. Mahnung nach 21, 2. Mahnung nach 35 Tagen, mit Zinsen und Pauschale",
        7,
        21,
        35,
        zinsen_aktiv=True,
        pauschale_aktiv=True,
    ),
    "konsequent": Vorlage(
        "Konsequent",
        "Erinnerung nach 5, 1. Mahnung nach 15, 2. Mahnung nach 25 Tagen, mit Zinsen und Pauschale",
        5,
        15,
        25,
        zinsen_aktiv=True,
        pauschale_aktiv=True,
    ),
}


@dataclass
class Schritt:
    nummer: int
    titel: str
    erledigt: bool
    text: str


def schritte(firma: Firma) -> list[Schritt]:
    verbindung = Verbindung.objects.fuer(firma).filter(status=Verbindung.Status.AKTIV).first()
    verbunden = bool(verbindung and verbindung.aktiv)
    importiert = bool(verbunden and verbindung and verbindung.erstimport_fertig)
    offen = kontakte_ohne_kundentyp(firma).count()
    return [
        Schritt(
            1,
            "Lexware verbinden",
            importiert,
            "Verbunden, Daten importiert."
            if importiert
            else ("Verbunden, der Erstimport läuft." if verbunden else "API-Schlüssel hinterlegen."),
        ),
        Schritt(
            2,
            "Kundentypen setzen",
            importiert and offen == 0,
            f"Bei {offen} Kunden mit offenen Posten fehlt der Kundentyp."
            if offen
            else "Alle Kunden mit offenen Posten haben einen Kundentyp.",
        ),
        Schritt(
            3,
            "Mahnplan wählen",
            firma.mahnplan_bestaetigt_am is not None,
            "Mahnplan bestätigt." if firma.mahnplan_bestaetigt_am else "Wählen Sie, wann erinnert und gemahnt wird.",
        ),
        Schritt(
            4,
            "Probelauf ansehen",
            firma.einrichtung_fertig_am is not None,
            "Einrichtung abgeschlossen."
            if firma.einrichtung_fertig_am
            else "Sehen Sie, was Belegfluss heute vorschlagen würde.",
        ),
    ]


def mahnplan_vorlage(firma: Firma, nutzer: Nutzer, schluessel: str) -> Mahnplan:
    vorlage = VORLAGEN[schluessel]
    with transaction.atomic():
        plan = mahnplan_fuer(firma)
        for feld, wert in vorlage.werte().items():
            setattr(plan, feld, wert)
        plan.full_clean()
        plan.geaendert = timezone.now()
        plan.save()
        firma.mahnplan_bestaetigt_am = timezone.now()
        firma.save(update_fields=["mahnplan_bestaetigt_am"])
        protokolliere(firma, "mahnplan.geaendert", nutzer=nutzer, objekt=plan, daten={"vorlage": schluessel})
    return plan


def abschliessen(firma: Firma, nutzer: Nutzer) -> None:
    firma.einrichtung_fertig_am = timezone.now()
    firma.save(update_fields=["einrichtung_fertig_am"])
    protokolliere(firma, "einrichtung.abgeschlossen", nutzer=nutzer, objekt=firma)
