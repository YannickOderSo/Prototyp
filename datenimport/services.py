"""Ablauf eines Imports: hochladen → zuordnen → Vorschau → Freigabe → ausführen (H1–H9, ADR-008).

Kunden und Artikel werden als Job in Lexware angelegt. Jede angelegte Zeile wird sofort im Ergebnis vermerkt,
damit ein Neuversuch nach einem Abbruch nichts doppelt anlegt. Offene Posten werden direkt im Cockpit angelegt
(Quelle „import“), nie in Lexware.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from accounts.models import Firma, Nutzer
from audit.services import protokolliere
from connectors.base import AccountingConnector, ArticleDraft, ContactDraft
from connectors.fehler import ConnectorFehler, NichtAutorisiert
from connectors.models import Verbindung
from connectors.services import aktive_verbindung
from jobs.queue import enqueue
from ledger.abgleich import kontakt_speichern
from ledger.models import Artikel, Beleg, Kontakt, Kundentyp

from . import vorschau
from .felder import fehlende_pflichtfelder, vorschlagen
from .lesen import Tabelle, lesen
from .models import ImportVorgang

log = logging.getLogger(__name__)


class ImportNichtMoeglich(Exception):
    """Für den Nutzer verständlicher Grund, warum ein Schritt nicht geht."""


def hochladen(firma: Firma, nutzer: Nutzer, art: str, dateiname: str, daten: bytes, blatt: str = "") -> ImportVorgang:
    tabelle: Tabelle = lesen(dateiname, daten, blatt or None)
    vorgang = ImportVorgang.objects.create(
        firma=firma,
        art=art,
        dateiname=dateiname[:255],
        blatt=tabelle.blatt,
        spalten=tabelle.spalten,
        zeilen=tabelle.zeilen,
        zuordnung=vorschlagen(art, tabelle.spalten),
        erstellt_von=nutzer,
        ergebnis={"blaetter": tabelle.blaetter},
    )
    protokolliere(
        firma,
        "import.hochgeladen",
        nutzer=nutzer,
        objekt=vorgang,
        daten={"art": art, "zeilen": len(tabelle.zeilen), "datei": dateiname[:100]},
    )
    return vorgang


def zuordnung_speichern(
    vorgang: ImportVorgang, zuordnung: dict[str, int], standardwerte: dict[str, str], kundentyp_uebernehmen: bool
) -> list[str]:
    """Speichert die Zuordnung und berechnet die Vorschau. Gibt fehlende Pflichtfelder zurück (dann keine Vorschau)."""
    aktuell = ImportVorgang.objects.filter(pk=vorgang.pk).values_list("status", flat=True).first()
    if aktuell not in (ImportVorgang.Status.ZUORDNUNG, ImportVorgang.Status.VORSCHAU):
        raise ImportNichtMoeglich("Dieser Import ist bereits freigegeben oder verworfen.")
    vorgang.zuordnung = {k: v for k, v in zuordnung.items() if 0 <= v < len(vorgang.spalten)}
    vorgang.standardwerte = standardwerte
    vorgang.kundentyp_uebernehmen = kundentyp_uebernehmen
    fehlend = fehlende_pflichtfelder(vorgang.art, vorgang.zuordnung)
    if fehlend:
        vorgang.status = ImportVorgang.Status.ZUORDNUNG
        vorgang.vorschau = []
    else:
        vorgang.vorschau = vorschau.berechnen(vorgang)
        vorgang.status = ImportVorgang.Status.VORSCHAU
    vorgang.save()
    return fehlend


def freigeben(vorgang: ImportVorgang, nutzer: Nutzer) -> None:
    """Freigabe durch Inhaber oder Freigeber (die View prüft Rolle und zweiten Faktor)."""
    with transaction.atomic():
        vorgang = ImportVorgang.objects.select_for_update().get(pk=vorgang.pk)
        if vorgang.status != ImportVorgang.Status.VORSCHAU:
            raise ImportNichtMoeglich("Dieser Import ist nicht freigabebereit.")
        # Vorschau unmittelbar vor der Freigabe neu berechnen: inzwischen angelegte Dubletten fallen heraus
        vorgang.vorschau = vorschau.berechnen(vorgang)
        if not vorgang.anzahl("neu"):
            raise ImportNichtMoeglich("Es gibt keine neuen Einträge zum Importieren.")
        verbindung = aktive_verbindung(vorgang.firma) if vorgang.art != ImportVorgang.Art.POSTEN else None
        if vorgang.art != ImportVorgang.Art.POSTEN and verbindung is None:
            raise ImportNichtMoeglich("Keine aktive Verbindung zu Lexware.")
        vorgang.status = ImportVorgang.Status.FREIGEGEBEN
        vorgang.freigegeben_von = nutzer
        vorgang.freigegeben_am = timezone.now()
        vorgang.ergebnis = {**vorgang.ergebnis, "zeilen": {}}
        vorgang.save()
        protokolliere(
            vorgang.firma,
            "import.freigegeben",
            nutzer=nutzer,
            objekt=vorgang,
            daten={"art": vorgang.art, "neu": vorgang.anzahl("neu")},
        )
        if verbindung is not None:
            enqueue(
                "datenimport.ausfuehren",
                {"verbindung_id": verbindung.pk, "vorgang_id": vorgang.pk},
                firma=vorgang.firma,
                eindeutig=f"import:{vorgang.pk}",
            )
    if vorgang.art == ImportVorgang.Art.POSTEN:
        posten_anlegen(vorgang)


def verwerfen(vorgang: ImportVorgang, nutzer: Nutzer) -> None:
    with transaction.atomic():
        gesperrt = ImportVorgang.objects.select_for_update().get(pk=vorgang.pk)
        if gesperrt.status in (ImportVorgang.Status.FREIGEGEBEN, ImportVorgang.Status.FERTIG):
            raise ImportNichtMoeglich("Ein freigegebener Import kann nicht mehr verworfen werden.")
        gesperrt.status = ImportVorgang.Status.VERWORFEN
        gesperrt.save(update_fields=["status"])
        vorgang.status = gesperrt.status
        protokolliere(vorgang.firma, "import.verworfen", nutzer=nutzer, objekt=vorgang)


def _vermerken(vorgang: ImportVorgang, nr: int, eintrag: dict[str, Any]) -> None:
    vorgang.ergebnis.setdefault("zeilen", {})[str(nr)] = eintrag
    ImportVorgang.objects.filter(pk=vorgang.pk).update(ergebnis=vorgang.ergebnis)


def _abschliessen(vorgang: ImportVorgang) -> None:
    zeilen = vorgang.ergebnis.get("zeilen", {})
    vorgang.ergebnis["angelegt"] = sum(1 for e in zeilen.values() if e.get("id"))
    vorgang.ergebnis["fehler"] = sum(1 for e in zeilen.values() if e.get("fehler"))
    vorgang.status = ImportVorgang.Status.FERTIG
    vorgang.save(update_fields=["ergebnis", "status"])
    protokolliere(
        vorgang.firma,
        "import.fertig",
        nutzer=vorgang.freigegeben_von,
        objekt=vorgang,
        daten={"art": vorgang.art, "angelegt": vorgang.ergebnis["angelegt"], "fehler": vorgang.ergebnis["fehler"]},
    )


def kunden_anlegen(vorgang: ImportVorgang, connector: AccountingConnector) -> None:
    for zeile in vorgang.vorschau:
        if zeile["status"] != "neu" or str(zeile["nr"]) in vorgang.ergebnis.get("zeilen", {}):
            continue
        d = zeile["daten"]
        notiz = f"Kundennummer aus Excel: {d['kundennummer']}" if d["kundennummer"] else ""
        entwurf = ContactDraft(
            name=d["name"],
            ist_firma=d["ist_firma"],
            vorname=d["vorname"],
            email=d["email"],
            strasse=d["strasse"],
            plz=d["plz"],
            ort=d["ort"],
            land=d["land"],
            telefon=d["telefon"],
            notiz=notiz,
            ansprechpartner_vorname=d["ansprechpartner_vorname"],
            ansprechpartner_nachname=d["ansprechpartner_nachname"],
        )
        try:
            extern_id = connector.create_contact(entwurf)
        except NichtAutorisiert:
            raise
        except ConnectorFehler as fehler:
            if fehler.wiederholbar:
                raise
            _vermerken(vorgang, zeile["nr"], {"fehler": f"{fehler.meldung} ({str(fehler)[:120]})"})
            continue
        _vermerken(vorgang, zeile["nr"], {"id": extern_id})
        protokolliere(
            vorgang.firma,
            "lexware.kontakt_angelegt",
            nutzer=vorgang.freigegeben_von,
            objekt=vorgang,
            daten={"zeile": zeile["nr"], "id": extern_id},
        )
        geladen = connector.get_contact(extern_id)
        kontakt = (
            kontakt_speichern(vorgang.firma, geladen)
            if geladen
            else Kontakt.objects.create(firma=vorgang.firma, extern_id=extern_id, name=d["name"], email=d["email"])
        )
        kontakt.excel_nummer = d["kundennummer"]
        felder = ["excel_nummer"]
        if vorgang.kundentyp_uebernehmen and d["kundentyp"] in (Kundentyp.PRIVAT, Kundentyp.UNTERNEHMER):
            kontakt.kundentyp = d["kundentyp"]
            felder.append("kundentyp")
            protokolliere(
                vorgang.firma,
                "kontakt.kundentyp_gesetzt",
                nutzer=vorgang.freigegeben_von,
                objekt=kontakt,
                daten={"alt": "unbekannt", "neu": d["kundentyp"], "per": "import"},
            )
        kontakt.save(update_fields=felder)
    _abschliessen(vorgang)


def artikel_anlegen(vorgang: ImportVorgang, connector: AccountingConnector) -> None:
    for zeile in vorgang.vorschau:
        if zeile["status"] != "neu" or str(zeile["nr"]) in vorgang.ergebnis.get("zeilen", {}):
            continue
        d = zeile["daten"]
        entwurf = ArticleDraft(
            bezeichnung=d["bezeichnung"],
            typ=d["typ"],
            einheit=d["einheit"],
            netto=Decimal(d["netto"]),
            steuersatz=Decimal(d["steuersatz"]),
            artikelnummer=d["artikelnummer"],
        )
        try:
            extern_id = connector.create_article(entwurf)
        except NichtAutorisiert:
            raise
        except ConnectorFehler as fehler:
            if fehler.wiederholbar:
                raise
            _vermerken(vorgang, zeile["nr"], {"fehler": f"{fehler.meldung} ({str(fehler)[:120]})"})
            continue
        _vermerken(vorgang, zeile["nr"], {"id": extern_id})
        protokolliere(
            vorgang.firma,
            "lexware.artikel_angelegt",
            nutzer=vorgang.freigegeben_von,
            objekt=vorgang,
            daten={"zeile": zeile["nr"], "id": extern_id},
        )
        Artikel.objects.update_or_create(
            firma=vorgang.firma,
            extern_id=extern_id,
            defaults={
                "bezeichnung": d["bezeichnung"],
                "einheit": d["einheit"],
                "netto": Decimal(d["netto"]),
                "steuersatz": Decimal(d["steuersatz"]),
                "typ": d["typ"],
                "artikelnummer": d["artikelnummer"],
            },
        )
    _abschliessen(vorgang)


def posten_anlegen(vorgang: ImportVorgang) -> None:
    """Alte offene Rechnungen nur im Cockpit (ADR-008): nie in Lexware, vom Abgleich ausgenommen."""
    with transaction.atomic():
        for zeile in vorgang.vorschau:
            if zeile["status"] != "neu":
                continue
            d = zeile["daten"]
            kontakt = Kontakt.objects.fuer(vorgang.firma).get(pk=d["kontakt_id"])
            faellig = date.fromisoformat(d["faellig_am"]) if d["faellig_am"] else None
            beleg = Beleg.objects.create(
                firma=vorgang.firma,
                extern_id=f"import-{vorgang.pk}-{zeile['nr']}",
                quelle=Beleg.Quelle.IMPORT,
                import_vorgang=vorgang,
                art=Beleg.Art.RECHNUNG,
                nummer=d["nummer"],
                belegdatum=date.fromisoformat(d["belegdatum"]),
                faellig_am=faellig,
                kontakt=kontakt,
                kontakt_name=kontakt.name,
                brutto=Decimal(d["brutto"]),
                offen=Decimal(d["offen"]),
                status=Beleg.Status.UEBERFAELLIG if faellig and faellig < timezone.localdate() else Beleg.Status.OFFEN,
            )
            vorgang.ergebnis.setdefault("zeilen", {})[str(zeile["nr"])] = {"id": beleg.extern_id}
        _abschliessen(vorgang)


def ausfuehren(verbindung: Verbindung, connector: AccountingConnector, vorgang_id: int) -> None:
    vorgang = ImportVorgang.objects.fuer(verbindung.firma).filter(pk=vorgang_id).first()
    if vorgang is None or vorgang.status != ImportVorgang.Status.FREIGEGEBEN:
        return
    if vorgang.art == ImportVorgang.Art.KUNDEN:
        kunden_anlegen(vorgang, connector)
    elif vorgang.art == ImportVorgang.Art.ARTIKEL:
        artikel_anlegen(vorgang, connector)


def importierte_status_aktualisieren(firma: Firma) -> int:
    """Importierte offene Posten werden mit Ablauf der Fälligkeit überfällig (Lexware-Posten setzt der Abgleich)."""
    return (
        Beleg.objects.fuer(firma)
        .filter(quelle=Beleg.Quelle.IMPORT, status=Beleg.Status.OFFEN, faellig_am__lt=timezone.localdate())
        .update(status=Beleg.Status.UEBERFAELLIG)
    )


def zahlung_eintragen(beleg: Beleg, nutzer: Nutzer, bezahlt_am: date | None, offen: Decimal | None) -> None:
    """H7: Zahlstatus importierter Posten pflegt der Betrieb im Cockpit."""
    if not beleg.importiert:
        raise ImportNichtMoeglich("Der Zahlstatus von Lexware-Rechnungen kommt aus Lexware.")
    alt = {"offen": str(beleg.offen), "status": beleg.status}
    if bezahlt_am is not None:
        beleg.offen = Decimal("0.00")
        beleg.status = Beleg.Status.BEZAHLT
        beleg.bezahlt_am = bezahlt_am
    elif offen is not None:
        if offen < 0 or offen > beleg.brutto:
            raise ImportNichtMoeglich("Der offene Betrag muss zwischen 0 und dem Rechnungsbetrag liegen.")
        beleg.offen = offen
        if offen == 0:
            beleg.status, beleg.bezahlt_am = Beleg.Status.BEZAHLT, timezone.localdate()
    else:
        raise ImportNichtMoeglich("Bitte Zahldatum oder neuen offenen Betrag angeben.")
    beleg.save(update_fields=["offen", "status", "bezahlt_am"])
    protokolliere(
        beleg.firma,
        "beleg.zahlung_manuell",
        nutzer=nutzer,
        objekt=beleg,
        daten={"alt": alt, "neu": {"offen": str(beleg.offen), "status": beleg.status}},
    )
