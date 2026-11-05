"""Adapter-Schnittstelle zum Bestandstool (Lexware Office, später sevdesk).

Alle Geldbeträge sind `Decimal` (kaufmännisch auf Cent gerundet), alle Fälligkeiten `date` in Europe/Berlin.
Die Datentypen sind bewusst unabhängig vom Lexware-Format, damit Cockpit und Mahnautomatik
unverändert gegen einen zweiten Adapter laufen (G1).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Protocol

CENT = Decimal("0.01")

BelegArt = Literal["rechnung", "abschlag", "angebot"]
BelegStatus = Literal["entwurf", "offen", "ueberfaellig", "bezahlt", "storniert"]


def geld(wert: object) -> Decimal:
    """Wandelt API-Zahlen ohne Umweg über float in Decimal mit Cent-Rundung (ROUND_HALF_UP)."""
    if wert is None or wert == "":
        return Decimal("0.00")
    return Decimal(str(wert)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CompanyInfo:
    organisation_id: str
    firmenname: str
    verbindungs_id: str = ""
    steuerart: str = "net"
    kleinunternehmer: bool = False


@dataclass(frozen=True)
class Receivable:
    """Offener Posten (Rechnung oder Abschlagsrechnung) als Spiegel aus dem Bestandstool."""

    extern_id: str
    art: BelegArt
    nummer: str
    belegdatum: date | None
    faellig_am: date | None
    kontakt_extern_id: str | None
    kontakt_name: str
    brutto: Decimal
    offen: Decimal
    status: BelegStatus
    aktualisiert_extern: datetime | None = None


@dataclass(frozen=True)
class PaymentStatus:
    offen: Decimal
    status: BelegStatus
    bezahlt_am: date | None = None
    zahlungen: tuple[tuple[date | None, Decimal], ...] = ()

    @property
    def bezahlt(self) -> bool:
        return self.status == "bezahlt" or (self.status != "entwurf" and self.offen <= 0)


@dataclass(frozen=True)
class Contact:
    extern_id: str
    name: str
    email: str = ""
    kundennummer: str = ""
    ist_unternehmen: bool | None = None
    archiviert: bool = False


@dataclass(frozen=True)
class Article:
    extern_id: str
    bezeichnung: str
    einheit: str
    netto: Decimal
    steuersatz: Decimal
    typ: Literal["PRODUCT", "SERVICE"]
    artikelnummer: str = ""
    archiviert: bool = False


@dataclass(frozen=True)
class DraftLine:
    """Position eines Entwurfs. Preis und Steuersatz stammen IMMER aus einem Artikel des Bestandstools."""

    name: str
    menge: Decimal
    einheit: str
    netto: Decimal
    steuersatz: Decimal
    artikel_extern_id: str | None = None
    artikel_typ: Literal["PRODUCT", "SERVICE"] | None = None
    beschreibung: str = ""


@dataclass(frozen=True)
class InvoiceDraft:
    kontakt_extern_id: str
    belegdatum: date
    positionen: tuple[DraftLine, ...]
    leistung_von: date | None = None
    leistung_bis: date | None = None
    titel: str = "Rechnung"
    einleitung: str = ""
    bemerkung: str = ""
    steuerart: str = "net"


@dataclass(frozen=True)
class QuotationDraft:
    kontakt_extern_id: str
    belegdatum: date
    gueltig_bis: date
    positionen: tuple[DraftLine, ...]
    titel: str = "Angebot"
    einleitung: str = ""
    bemerkung: str = ""
    steuerart: str = "net"


@dataclass(frozen=True)
class DunningFees:
    """Inhalt einer Mahnung im Bestandstool. Zinsen und Pauschale sind nicht umsatzsteuerbar (0 %)."""

    stufe: int
    rechnungsnummer: str
    offen: Decimal
    zinsen: Decimal = Decimal("0.00")
    pauschale: Decimal = Decimal("0.00")
    zinsen_text: str = ""
    einleitung: str = ""
    bemerkung: str = ""
    belegdatum: date | None = None


@dataclass(frozen=True)
class ExternalRef:
    art: Literal["invoice", "downpaymentinvoice", "quotation", "dunning"]
    extern_id: str
    url: str = ""


@dataclass(frozen=True)
class WebhookAbo:
    extern_id: str
    ereignis: str
    callback_url: str
    extra: dict[str, str] = field(default_factory=dict)


class AccountingConnector(Protocol):
    """Gemeinsame Schnittstelle aller Bestandstool-Adapter (Integration-Lexware.md)."""

    def test(self) -> CompanyInfo: ...

    def list_open_receivables(self, updated_since: date | None = None) -> Iterable[Receivable]: ...

    def list_receivables(self, status: str, updated_since: date | None = None) -> Iterable[Receivable]: ...

    def get_receivable(self, voucher_id: str) -> Receivable | None: ...

    def get_payment_status(self, voucher_id: str) -> PaymentStatus: ...

    def list_contacts(self) -> Iterable[Contact]: ...

    def get_contact(self, contact_id: str) -> Contact | None: ...

    def list_articles(self) -> Iterable[Article]: ...

    def create_invoice_draft(self, draft: InvoiceDraft) -> ExternalRef: ...

    def create_quotation_draft(self, draft: QuotationDraft) -> ExternalRef: ...

    def create_dunning_draft(self, invoice_id: str, fees: DunningFees) -> ExternalRef | None: ...

    def get_pdf(self, ref: ExternalRef) -> bytes: ...

    def list_open_quotations(self) -> Iterable[Receivable]: ...

    def get_quotation_positions(self, quotation_id: str) -> list[tuple[str, Decimal]]: ...

    def register_webhooks(self, callback_url: str) -> list[str]: ...

    def delete_webhooks(self, ids: Iterable[str]) -> None: ...
