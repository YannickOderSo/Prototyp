"""Vorschau je Zeile: neu, Dublette, bezahlt oder Fehler mit Grund (H3). Ändert nichts, berechnet nur.

Dubletten werden gegen die Kunden, Artikel und Belege in Belegfluss (mit Lexware: der Spiegel) und innerhalb der
Datei erkannt. Kunden für offene Posten werden über die Kundennummer (Excel-Nummer oder Lexware-Nummer) oder den
genauen Namen gefunden; mehrdeutige Treffer sind ein Fehler, nie eine Vermutung.

Ohne Lexware (M9-08, ADR-008 Nachtrag): Ein unbekannter Kunde eines offenen Postens wird in der Vorschau als
„wird neu angelegt“ markiert und bei der Freigabe nur in Belegfluss angelegt.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone

from connectors.services import ohne_lexware
from ledger.models import Artikel, Beleg, Kontakt

from . import werte
from .models import ImportVorgang

CENT = Decimal("0.01")
LAENDER = {
    "de": "DE",
    "deutschland": "DE",
    "germany": "DE",
    "d": "DE",
    "at": "AT",
    "österreich": "AT",
    "oesterreich": "AT",
    "austria": "AT",
    "ch": "CH",
    "schweiz": "CH",
    "switzerland": "CH",
    "lu": "LU",
    "luxemburg": "LU",
    "nl": "NL",
    "niederlande": "NL",
    "fr": "FR",
    "frankreich": "FR",
}


def _schluessel(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class _Zeilen:
    def __init__(self, vorgang: ImportVorgang) -> None:
        self.vorgang = vorgang

    def wert(self, zeile: list[str], feld: str) -> str:
        index = self.vorgang.zuordnung.get(feld)
        if index is None or index >= len(zeile):
            return ""
        return str(zeile[index]).strip()


def _land(text: str) -> str:
    roh = text.strip().lower()
    if not roh:
        return "DE"
    if roh in LAENDER:
        return LAENDER[roh]
    if re.fullmatch(r"[a-z]{2}", roh):
        return roh.upper()
    raise werte.WertFehler(f"Land „{text}“ unbekannt (Ländercode wie DE angeben)")


def _wo(v: ImportVorgang) -> str:
    return "in Belegfluss" if ohne_lexware(v.firma) else "in Lexware"


def _kunden(v: ImportVorgang) -> list[dict[str, Any]]:
    z = _Zeilen(v)
    wo = _wo(v)
    vorhanden_name = {_schluessel(k.name): k.name for k in Kontakt.objects.fuer(v.firma)}
    vorhanden_mail = {k.email.lower(): k.name for k in Kontakt.objects.fuer(v.firma) if k.email}
    gesehen: dict[str, int] = {}
    ergebnis = []
    for i, zeile in enumerate(v.zeilen):
        nr = i + 2
        try:
            firma, nachname, vorname = z.wert(zeile, "firma"), z.wert(zeile, "nachname"), z.wert(zeile, "vorname")
            if firma:
                name, ist_firma, ansprechpartner = firma, True, (vorname, nachname)
            elif nachname:
                ist_firma = werte.ist_firma(nachname, z.wert(zeile, "art"))
                name, ansprechpartner = nachname, ("", "")
            else:
                raise werte.WertFehler("Name fehlt")
            daten: dict[str, Any] = {
                "name": name[:250],
                "vorname": "" if ist_firma else vorname[:100],
                "ist_firma": ist_firma,
                "ansprechpartner_vorname": ansprechpartner[0][:100],
                "ansprechpartner_nachname": ansprechpartner[1][:100],
                "email": werte.email(z.wert(zeile, "email")),
                "strasse": z.wert(zeile, "strasse")[:200],
                "plz": z.wert(zeile, "plz")[:10],
                "ort": z.wert(zeile, "ort")[:100],
                "land": _land(z.wert(zeile, "land")),
                "telefon": z.wert(zeile, "telefon")[:50],
                "kundennummer": z.wert(zeile, "kundennummer")[:50],
                "kundentyp": werte.kundentyp(z.wert(zeile, "kundentyp")),
            }
        except werte.WertFehler as fehler:
            ergebnis.append({"nr": nr, "status": "fehler", "grund": str(fehler), "anzeige": " ".join(zeile[:3])})
            continue
        anzeige = " ".join(x for x in (daten["vorname"], daten["name"]) if x)
        schluessel = _schluessel(anzeige)
        if schluessel in vorhanden_name or _schluessel(daten["name"]) in vorhanden_name:
            status, grund = "dublette", f"Schon {wo} vorhanden"
        elif daten["email"] and daten["email"] in vorhanden_mail:
            status, grund = "dublette", f"E-Mail gehört schon zu „{vorhanden_mail[daten['email']]}“ {wo}"
        elif schluessel in gesehen:
            status, grund = "dublette", f"Doppelt in der Datei (Zeile {gesehen[schluessel]})"
        else:
            status, grund = "neu", ""
            gesehen[schluessel] = nr
        ergebnis.append({"nr": nr, "status": status, "grund": grund, "anzeige": anzeige, "daten": daten})
    return ergebnis


def _artikel(v: ImportVorgang) -> list[dict[str, Any]]:
    z = _Zeilen(v)
    vorhanden_nummer = {a.artikelnummer.lower() for a in Artikel.objects.fuer(v.firma) if a.artikelnummer}
    vorhanden_name = {_schluessel(a.bezeichnung) for a in Artikel.objects.fuer(v.firma)}
    gesehen: dict[str, int] = {}
    ergebnis = []
    for i, zeile in enumerate(v.zeilen):
        nr = i + 2
        try:
            bezeichnung = z.wert(zeile, "bezeichnung")
            if not bezeichnung:
                raise werte.WertFehler("Bezeichnung fehlt")
            einheit = z.wert(zeile, "einheit") or str(v.standardwerte.get("einheit") or "")
            if not einheit:
                raise werte.WertFehler("Einheit fehlt")
            satz_text = z.wert(zeile, "steuersatz") or str(v.standardwerte.get("steuersatz") or "")
            if not satz_text:
                raise werte.WertFehler("Steuersatz fehlt (Spalte zuordnen oder Standardwert wählen)")
            satz = werte.steuersatz(satz_text)
            typ = werte.artikeltyp(z.wert(zeile, "typ")) or str(v.standardwerte.get("typ") or "")
            if typ not in ("SERVICE", "PRODUCT"):
                raise werte.WertFehler("Art fehlt (Dienstleistung oder Material)")
            netto_text, brutto_text = z.wert(zeile, "preis_netto"), z.wert(zeile, "preis_brutto")
            if netto_text:
                netto = werte.betrag(netto_text)
            elif brutto_text:
                netto = (werte.zahl(brutto_text) / (1 + satz / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
            else:
                raise werte.WertFehler("Preis fehlt")
            if netto < 0:
                raise werte.WertFehler("Preis ist negativ")
            daten: dict[str, Any] = {
                "bezeichnung": bezeichnung[:250],
                "einheit": einheit[:50],
                "netto": str(netto),
                "steuersatz": str(satz),
                "typ": typ,
                "artikelnummer": z.wert(zeile, "artikelnummer")[:50],
            }
        except werte.WertFehler as fehler:
            ergebnis.append({"nr": nr, "status": "fehler", "grund": str(fehler), "anzeige": " ".join(zeile[:2])})
            continue
        schluessel = daten["artikelnummer"].lower() or _schluessel(daten["bezeichnung"])
        if (daten["artikelnummer"] and daten["artikelnummer"].lower() in vorhanden_nummer) or (
            _schluessel(daten["bezeichnung"]) in vorhanden_name
        ):
            status, grund = "dublette", "Schon in Lexware vorhanden"
        elif schluessel in gesehen:
            status, grund = "dublette", f"Doppelt in der Datei (Zeile {gesehen[schluessel]})"
        else:
            status, grund = "neu", ""
            gesehen[schluessel] = nr
        ergebnis.append({"nr": nr, "status": status, "grund": grund, "anzeige": daten["bezeichnung"], "daten": daten})
    return ergebnis


def _kunde_finden(kontakte: list[Kontakt], nummer: str, name: str) -> Kontakt | None:
    """Eindeutiger Treffer, None wenn keiner; mehrdeutig ist ein Fehler."""
    if nummer:
        treffer = [k for k in kontakte if nummer in (k.excel_nummer, k.kundennummer)]
        if len(treffer) == 1:
            return treffer[0]
        if len(treffer) > 1:
            raise werte.WertFehler(f"Kundennummer „{nummer}“ ist mehrdeutig")
    treffer = [k for k in kontakte if _schluessel(k.name) == _schluessel(name)] if name else []
    if len(treffer) == 1:
        return treffer[0]
    if len(treffer) > 1:
        raise werte.WertFehler(f"Kunde „{name}“ ist mehrdeutig, bitte Kundennummer angeben")
    return None


def _posten(v: ImportVorgang) -> list[dict[str, Any]]:
    z = _Zeilen(v)
    lokal = ohne_lexware(v.firma)
    neue_kunden: dict[str, int] = {}
    kontakte = list(Kontakt.objects.fuer(v.firma))
    vorhanden = {_schluessel(n) for n in Beleg.objects.fuer(v.firma).values_list("nummer", flat=True) if n}
    gesehen: dict[str, int] = {}
    heute = timezone.localdate()
    ergebnis = []
    for i, zeile in enumerate(v.zeilen):
        nr = i + 2
        try:
            nummer = z.wert(zeile, "rechnungsnummer")
            if not nummer:
                raise werte.WertFehler("Rechnungsnummer fehlt")
            belegdatum = werte.datum(z.wert(zeile, "rechnungsdatum"))
            faellig_text = z.wert(zeile, "faellig_am")
            faellig = werte.datum(faellig_text) if faellig_text else None
            if faellig and faellig < belegdatum:
                raise werte.WertFehler("Fälligkeit liegt vor dem Rechnungsdatum")
            betrag = werte.betrag(z.wert(zeile, "betrag"))
            if betrag <= 0:
                raise werte.WertFehler("Betrag muss größer als 0 sein")
            bezahlt_text, offen_text = z.wert(zeile, "bezahlt"), z.wert(zeile, "offen")
            bezahlt = werte.betrag(bezahlt_text) if bezahlt_text else Decimal("0.00")
            offen = werte.betrag(offen_text) if offen_text else betrag - bezahlt
            if offen > betrag:
                raise werte.WertFehler("Offener Betrag ist größer als der Rechnungsbetrag")
            name, kundennummer = z.wert(zeile, "kunde"), z.wert(zeile, "kundennummer")
            kunde = _kunde_finden(kontakte, kundennummer, name)
            if kunde is None and not lokal:
                raise werte.WertFehler(
                    f"Kunde „{name or kundennummer}“ nicht in Lexware, bitte zuerst Kunden importieren"
                )
            if kunde is None and not name:
                raise werte.WertFehler(f"Kundennummer „{kundennummer}“ unbekannt und kein Kundenname angegeben")
            email_text = z.wert(zeile, "kunde_email")
            daten: dict[str, Any] = {
                "nummer": nummer[:50],
                "belegdatum": belegdatum.isoformat(),
                "faellig_am": faellig.isoformat() if faellig else "",
                "brutto": str(betrag),
                "offen": str(offen),
                "kontakt_id": kunde.pk if kunde else None,
                "kunde": kunde.name if kunde else name[:250],
                "kunde_neu": kunde is None,
                "kunde_email": werte.email(email_text) if kunde is None and email_text else "",
                "kunde_nummer": kundennummer[:50] if kunde is None else "",
                "ueberfaellig": bool(faellig and faellig < heute),
            }
        except werte.WertFehler as fehler:
            ergebnis.append({"nr": nr, "status": "fehler", "grund": str(fehler), "anzeige": " ".join(zeile[:2])})
            continue
        anzeige = f"{daten['nummer']} · {daten['kunde']}"
        schluessel = _schluessel(daten["nummer"])
        if offen <= 0:
            status, grund = "bezahlt", "Bereits vollständig bezahlt, wird nicht importiert"
        elif schluessel in vorhanden:
            status, grund = "dublette", "Rechnungsnummer ist schon in Belegfluss (aus Lexware oder früherem Import)"
        elif schluessel in gesehen:
            status, grund = "dublette", f"Doppelt in der Datei (Zeile {gesehen[schluessel]})"
        else:
            status, grund = "neu", ""
            gesehen[schluessel] = nr
            if daten["kunde_neu"]:
                erste = neue_kunden.setdefault(_schluessel(daten["kunde"]), nr)
                grund = (
                    f"Kunde „{daten['kunde']}“ wird in Belegfluss neu angelegt (Kundentyp danach festlegen)."
                    if erste == nr
                    else f"Neuer Kunde „{daten['kunde']}“ wie in Zeile {erste}."
                )
        ergebnis.append({"nr": nr, "status": status, "grund": grund, "anzeige": anzeige, "daten": daten})
    return ergebnis


def berechnen(vorgang: ImportVorgang) -> list[dict[str, Any]]:
    return {"kunden": _kunden, "artikel": _artikel, "posten": _posten}[vorgang.art](vorgang)
