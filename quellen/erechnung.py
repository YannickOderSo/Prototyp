"""E-Rechnungen lesen (K2): ZUGFeRD/Factur-X (PDF mit eingebettetem XML), XRechnung als CII und als UBL.

Gelesen werden nur die Felder, die Cockpit und Mahnwesen brauchen (Bezeichnungen nach EN 16931):
BT-1 Nummer, BT-2 Datum, BT-3 Art, BT-5 Währung, BT-9 Fälligkeit, BT-20 Zahlungsbedingungen, BT-25 Bezug,
BT-27/BT-31 Verkäufer, BT-44/BT-48/BT-49/BT-58 Käufer mit Anschrift, BT-112 Brutto, BT-113 Vorauszahlung,
BT-115 Zahlbetrag.

Sicherheit: XML kommt aus fremder Hand. Geparst wird nur mit defusedxml, ohne DTD, ohne Entitäten, ohne externe
Verweise, mit Größenlimit. Eine Datei, die das verletzt, wird abgelehnt.
"""

from __future__ import annotations

import io
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from connectors.base import geld

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024

CII = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
UBL = {
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
UBL_RECHNUNG = "{urn:oasis:names:specification:ubl:schema:xsd:Invoice-2}Invoice"
UBL_GUTSCHRIFT = "{urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2}CreditNote"
CII_WURZEL = f"{{{CII['rsm']}}}CrossIndustryInvoice"

# Dateinamen eingebetteter Rechnungsdaten in ZUGFeRD 1/2 und Factur-X; sonst die einzige XML-Datei
EINGEBETTET = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "zugferd_invoice.xml")

GUTSCHRIFT_CODES = {"381", "396", "532"}
KORREKTUR_CODES = {"384"}
ABSCHLAG_CODES = {"326", "875"}


class ERechnungFehler(Exception):
    """Datei ist als E-Rechnung gemeint, aber nicht lesbar oder unsicher."""


class KeineERechnung(Exception):
    """Datei enthält keine strukturierten Rechnungsdaten (z. B. reines PDF)."""


@dataclass(frozen=True)
class Kaeufer:
    name: str = ""
    email: str = ""
    ustid: str = ""
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    land: str = ""

    @property
    def anschrift(self) -> str:
        zeilen = [self.name, self.strasse, " ".join(t for t in (self.plz, self.ort) if t)]
        if self.land and self.land.upper() != "DE":
            zeilen.append(self.land.upper())
        return "\n".join(z for z in zeilen if z)


@dataclass(frozen=True)
class ERechnung:
    format: str
    nummer: str
    art_code: str
    belegdatum: date | None
    faellig_am: date | None
    faelligkeit_aus: str
    waehrung: str
    verkaeufer: str
    verkaeufer_ustid: str
    kaeufer: Kaeufer
    brutto: Decimal
    vorauszahlung: Decimal
    zahlbetrag: Decimal
    bezug: str
    zahlungsbedingungen: str

    @property
    def art(self) -> str:
        if self.art_code in GUTSCHRIFT_CODES:
            return "gutschrift"
        if self.art_code in KORREKTUR_CODES:
            return "korrektur"
        if self.art_code in ABSCHLAG_CODES:
            return "abschlag"
        return "rechnung"

    def als_dict(self) -> dict[str, Any]:
        """JSON-taugliche Form für die Rechnungskopie (Beträge als Text, Daten ISO)."""
        werte = asdict(self)
        for feld in ("brutto", "vorauszahlung", "zahlbetrag"):
            werte[feld] = str(werte[feld])
        for feld in ("belegdatum", "faellig_am"):
            werte[feld] = werte[feld].isoformat() if werte[feld] else ""
        werte["art"] = self.art
        return werte


# ------------------------------------------------------------------ Einstieg


def lesen(dateiname: str, daten: bytes) -> ERechnung:
    """Liest eine Rechnungsdatei. KeineERechnung: PDF ohne XML (Weg über KI und Bestätigung, K5)."""
    if daten[:5] == b"%PDF-":
        return lesen_xml(_aus_pdf(daten), "zugferd")
    kopf = daten[:512].lstrip(b"\xef\xbb\xbf \t\r\n")
    if kopf.startswith(b"<"):
        return lesen_xml(daten, "")
    raise KeineERechnung(f"„{dateiname}“ ist weder PDF noch XML.")


def _aus_pdf(daten: bytes) -> bytes:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(daten) > MAX_PDF_BYTES:
        raise ERechnungFehler("Die PDF-Datei ist größer als 25 MB.")
    try:
        anhaenge = PdfReader(io.BytesIO(daten)).attachments
    except (PdfReadError, ValueError, KeyError, TypeError) as fehler:
        raise KeineERechnung("Die PDF-Datei ließ sich nicht öffnen.") from fehler
    namen = {name.lower(): name for name in anhaenge}
    for bekannt in EINGEBETTET:
        if bekannt in namen:
            return anhaenge[namen[bekannt]][0]
    xml = [name for name in anhaenge if name.lower().endswith(".xml")]
    if len(xml) == 1:
        return anhaenge[xml[0]][0]
    raise KeineERechnung("Die PDF-Datei enthält keine eingebetteten Rechnungsdaten (ZUGFeRD/Factur-X).")


def lesen_xml(daten: bytes, format_hinweis: str) -> ERechnung:
    if len(daten) > MAX_XML_BYTES:
        raise ERechnungFehler("Die XML-Datei ist größer als 5 MB.")
    try:
        wurzel = fromstring(daten, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as fehler:
        raise ERechnungFehler(
            "Die XML-Datei enthält eine DTD oder Entitäten und wird aus Sicherheitsgründen nicht gelesen."
        ) from fehler
    except ParseError as fehler:
        raise ERechnungFehler("Die XML-Datei ist nicht wohlgeformt.") from fehler
    if wurzel.tag == CII_WURZEL:
        return _cii(wurzel, format_hinweis or "xrechnung_cii")
    if wurzel.tag in (UBL_RECHNUNG, UBL_GUTSCHRIFT):
        return _ubl(wurzel)
    raise KeineERechnung("Die XML-Datei ist keine Rechnung im Format CII oder UBL.")


# ------------------------------------------------------------------ Hilfen


def _text(knoten: Element | None, pfad: str, ns: dict[str, str]) -> str:
    if knoten is None:
        return ""
    wert = knoten.findtext(pfad, default="", namespaces=ns)
    return " ".join(wert.split())[:500]


def _betrag(text: str) -> Decimal:
    if not text:
        return Decimal("0.00")
    try:
        return geld(Decimal(text))
    except (InvalidOperation, ValueError) as fehler:
        raise ERechnungFehler(f"Ungültiger Betrag „{text[:30]}“.") from fehler


def _datum_102(text: str) -> date | None:
    """CII-Datum im Format 102 (JJJJMMTT)."""
    text = text.strip()
    if re.fullmatch(r"\d{8}", text):
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:]))
        except ValueError:
            return None
    return None


def _datum_iso(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip()[:10]) if text.strip() else None
    except ValueError:
        return None


def _email(text: str) -> str:
    text = text.strip().removeprefix("mailto:")
    return text.lower() if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text) else ""


ZAHLUNGSZIEL = re.compile(
    r"(?:zahlbar|zahlungsziel|innerhalb|binnen|netto|ohne abzug|payable|within)"
    r"[^0-9]{0,40}?(\d{1,3})\s*(?:tage|tagen|days)",
    re.IGNORECASE,
)


def faelligkeit_aus_text(text: str, belegdatum: date | None) -> date | None:
    """BT-20 deuten, nur wenn eindeutig: „zahlbar innerhalb von 14 Tagen“ → Belegdatum + 14."""
    if not text or belegdatum is None:
        return None
    treffer = {int(t) for t in ZAHLUNGSZIEL.findall(text)}
    if len(treffer) != 1:
        return None
    tage = treffer.pop()
    return belegdatum + timedelta(days=tage) if 0 <= tage <= 180 else None


def _ergebnis(format_name: str, werte: dict[str, Any]) -> ERechnung:
    if not werte["nummer"]:
        raise ERechnungFehler("Die Rechnungsnummer (BT-1) fehlt.")
    faellig, aus = werte.pop("faellig_bt9"), "BT-9"
    if faellig is None:
        faellig = faelligkeit_aus_text(werte["zahlungsbedingungen"], werte["belegdatum"])
        aus = "BT-20" if faellig else ""
    if not werte["zahlbetrag_text"]:
        zahlbetrag = werte["brutto"] - werte["vorauszahlung"]
    else:
        zahlbetrag = _betrag(werte["zahlbetrag_text"])
    werte.pop("zahlbetrag_text")
    return ERechnung(format=format_name, faellig_am=faellig, faelligkeit_aus=aus, zahlbetrag=zahlbetrag, **werte)


# ------------------------------------------------------------------ CII (ZUGFeRD, Factur-X, XRechnung CII)


def _cii(wurzel: Element, format_name: str) -> ERechnung:
    ns = CII
    dokument = wurzel.find("rsm:ExchangedDocument", ns)
    handel = wurzel.find("rsm:SupplyChainTradeTransaction", ns)
    vereinbarung = handel.find("ram:ApplicableHeaderTradeAgreement", ns) if handel is not None else None
    abrechnung = handel.find("ram:ApplicableHeaderTradeSettlement", ns) if handel is not None else None
    verkaeufer = vereinbarung.find("ram:SellerTradeParty", ns) if vereinbarung is not None else None
    kaeufer = vereinbarung.find("ram:BuyerTradeParty", ns) if vereinbarung is not None else None
    summen = (
        abrechnung.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", ns) if abrechnung is not None else None
    )
    adresse = kaeufer.find("ram:PostalTradeAddress", ns) if kaeufer is not None else None
    faellig = None
    bedingungen = []
    if abrechnung is not None:
        for termin in abrechnung.findall("ram:SpecifiedTradePaymentTerms", ns):
            faellig = faellig or _datum_102(_text(termin, "ram:DueDateDateTime/udt:DateTimeString", ns))
            if beschreibung := _text(termin, "ram:Description", ns):
                bedingungen.append(beschreibung)
    email = _email(_text(kaeufer, "ram:URIUniversalCommunication/ram:URIID[@schemeID='EM']", ns)) or _email(
        _text(kaeufer, "ram:DefinedTradeContact/ram:EmailURIUniversalCommunication/ram:URIID", ns)
    )
    return _ergebnis(
        format_name,
        {
            "nummer": _text(dokument, "ram:ID", ns),
            "art_code": _text(dokument, "ram:TypeCode", ns) or "380",
            "belegdatum": _datum_102(_text(dokument, "ram:IssueDateTime/udt:DateTimeString", ns)),
            "faellig_bt9": faellig,
            "waehrung": _text(abrechnung, "ram:InvoiceCurrencyCode", ns) or "EUR",
            "verkaeufer": _text(verkaeufer, "ram:Name", ns),
            "verkaeufer_ustid": _text(verkaeufer, "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ns),
            "kaeufer": Kaeufer(
                name=_text(kaeufer, "ram:Name", ns),
                email=email,
                ustid=_text(kaeufer, "ram:SpecifiedTaxRegistration/ram:ID[@schemeID='VA']", ns),
                strasse=_text(adresse, "ram:LineOne", ns),
                plz=_text(adresse, "ram:PostcodeCode", ns),
                ort=_text(adresse, "ram:CityName", ns),
                land=_text(adresse, "ram:CountryID", ns),
            ),
            "brutto": _betrag(_text(summen, "ram:GrandTotalAmount", ns)),
            "vorauszahlung": _betrag(_text(summen, "ram:TotalPrepaidAmount", ns)),
            "zahlbetrag_text": _text(summen, "ram:DuePayableAmount", ns),
            "bezug": _text(abrechnung, "ram:InvoiceReferencedDocument/ram:IssuerAssignedID", ns),
            "zahlungsbedingungen": " ".join(bedingungen)[:500],
        },
    )


# ------------------------------------------------------------------ UBL (XRechnung UBL)


def _ubl(wurzel: Element) -> ERechnung:
    ns = UBL
    gutschrift = wurzel.tag == UBL_GUTSCHRIFT
    verkaeufer = wurzel.find("cac:AccountingSupplierParty/cac:Party", ns)
    kaeufer = wurzel.find("cac:AccountingCustomerParty/cac:Party", ns)
    adresse = kaeufer.find("cac:PostalAddress", ns) if kaeufer is not None else None
    summen = wurzel.find("cac:LegalMonetaryTotal", ns)
    endpunkt = kaeufer.find("cbc:EndpointID", ns) if kaeufer is not None else None
    email = ""
    if endpunkt is not None and (endpunkt.get("schemeID") or "").upper() == "EM":
        email = _email(endpunkt.text or "")
    email = email or _email(_text(kaeufer, "cac:Contact/cbc:ElectronicMail", ns))
    faellig = _datum_iso(_text(wurzel, "cbc:DueDate", ns)) or _datum_iso(
        _text(wurzel, "cac:PaymentMeans/cbc:PaymentDueDate", ns)
    )
    return _ergebnis(
        "xrechnung_ubl",
        {
            "nummer": _text(wurzel, "cbc:ID", ns),
            "art_code": _text(wurzel, "cbc:CreditNoteTypeCode" if gutschrift else "cbc:InvoiceTypeCode", ns)
            or ("381" if gutschrift else "380"),
            "belegdatum": _datum_iso(_text(wurzel, "cbc:IssueDate", ns)),
            "faellig_bt9": faellig,
            "waehrung": _text(wurzel, "cbc:DocumentCurrencyCode", ns) or "EUR",
            "verkaeufer": _text(verkaeufer, "cac:PartyLegalEntity/cbc:RegistrationName", ns)
            or _text(verkaeufer, "cac:PartyName/cbc:Name", ns),
            "verkaeufer_ustid": _text(verkaeufer, "cac:PartyTaxScheme/cbc:CompanyID", ns),
            "kaeufer": Kaeufer(
                name=_text(kaeufer, "cac:PartyLegalEntity/cbc:RegistrationName", ns)
                or _text(kaeufer, "cac:PartyName/cbc:Name", ns),
                email=email,
                ustid=_text(kaeufer, "cac:PartyTaxScheme/cbc:CompanyID", ns),
                strasse=_text(adresse, "cbc:StreetName", ns),
                plz=_text(adresse, "cbc:PostalZone", ns),
                ort=_text(adresse, "cbc:CityName", ns),
                land=_text(adresse, "cac:Country/cbc:IdentificationCode", ns),
            ),
            "brutto": _betrag(_text(summen, "cbc:TaxInclusiveAmount", ns)),
            "vorauszahlung": _betrag(_text(summen, "cbc:PrepaidAmount", ns)),
            "zahlbetrag_text": _text(summen, "cbc:PayableAmount", ns),
            "bezug": _text(wurzel, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID", ns),
            "zahlungsbedingungen": _text(wurzel, "cac:PaymentTerms/cbc:Note", ns),
        },
    )
