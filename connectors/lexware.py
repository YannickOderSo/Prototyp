"""Lexware Office Public API (https://developers.lexware.io/docs/, geprüft am 5. November 2026).

Grundsätze:
- Belege entstehen ausschließlich als Entwurf. `finalize` wird nie gesendet (ADR-001, B5);
  `_anfrage()` verweigert jede Anfrage, die `finalize` enthält.
- Höchstens 2 Anfragen pro Sekunde je Verbindung (Token-Bucket), 429 und 5xx mit Backoff und Jitter (B4).
- Geldbeträge werden ohne float als Decimal gelesen und als Zahl mit zwei Nachkommastellen geschrieben.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .base import (
    Article,
    ArticleDraft,
    BelegArt,
    BelegStatus,
    CompanyInfo,
    Contact,
    ContactDraft,
    DraftLine,
    DunningFees,
    ExternalRef,
    InvoiceDraft,
    PaymentStatus,
    QuotationDraft,
    Receivable,
    geld,
)
from .drossel import TokenBucket, eimer_fuer
from .fehler import (
    ConnectorFehler,
    Konflikt,
    NichtAutorisiert,
    NichtErreichbar,
    NichtGefunden,
    RateLimitUeberschritten,
    Validierungsfehler,
    VerboteneOperation,
)

log = logging.getLogger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
APP_URL = "https://app.lexware.de"
SEITENGROESSE = 250
MAX_WIEDERHOLUNGEN = 5

WEBHOOK_EREIGNISSE = (
    "invoice.created",
    "invoice.changed",
    "invoice.status.changed",
    "invoice.deleted",
    "payment.changed",
    "down-payment-invoice.status.changed",
    "contact.changed",
    "contact.created",
    "article.changed",
    "token.revoked",
)

_STATUS = {
    "draft": "entwurf",
    "open": "offen",
    "overdue": "ueberfaellig",
    "paid": "bezahlt",
    "paidoff": "bezahlt",
    "voided": "storniert",
}
_ART = {"invoice": "rechnung", "downpaymentinvoice": "abschlag", "quotation": "angebot"}
_PFAD = {
    "invoice": "invoices",
    "downpaymentinvoice": "down-payment-invoices",
    "quotation": "quotations",
    "dunning": "dunnings",
}


def zeitpunkt(tag: date) -> str:
    """Lexware erwartet Datum mit Uhrzeit und Zone, z. B. 2026-11-05T00:00:00.000+01:00."""
    versatz = datetime(tag.year, tag.month, tag.day, tzinfo=BERLIN).strftime("%z")
    return f"{tag.isoformat()}T00:00:00.000{versatz[:3]}:{versatz[3:]}"


def _datum(wert: str | None) -> date | None:
    if not wert:
        return None
    return datetime.fromisoformat(wert).astimezone(BERLIN).date()


def _zeit(wert: str | None) -> datetime | None:
    return datetime.fromisoformat(wert) if wert else None


_ZAHL = "__zahl__"


def _zahlen_vorbereiten(objekt: Any) -> Any:
    if isinstance(objekt, Decimal):
        return f"{_ZAHL}{objekt}"
    if isinstance(objekt, dict):
        return {k: _zahlen_vorbereiten(v) for k, v in objekt.items()}
    if isinstance(objekt, list | tuple):
        return [_zahlen_vorbereiten(v) for v in objekt]
    return objekt


def als_json(daten: dict[str, Any]) -> str:
    """JSON mit Decimal als Zahl (ohne Umweg über float)."""
    text = json.dumps(_zahlen_vorbereiten(daten), ensure_ascii=False)
    return re.sub(rf'"{_ZAHL}(-?\d+(?:\.\d+)?)"', r"\1", text)


def _pruefe_finalize(pfad: str, params: dict[str, Any] | None) -> None:
    if "finalize" in pfad.lower() or any("finalize" in str(k).lower() for k in (params or {})):
        raise VerboteneOperation("finalize ist verboten: die App legt im Bestandstool nur Entwürfe an")


class LexwareConnector:
    def __init__(
        self,
        api_schluessel: str,
        basis_url: str = "https://api.lexware.io",
        client: httpx.Client | None = None,
        eimer: TokenBucket | None = None,
        schlafen: Callable[[float], None] | None = None,
        timeout: float = 30.0,
    ) -> None:
        if not api_schluessel:
            raise NichtAutorisiert("Kein API-Schlüssel hinterlegt")
        self._schluessel = api_schluessel
        self.basis_url = basis_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        kennung = hashlib.sha256(api_schluessel.encode()).hexdigest()[:16]
        self._eimer = eimer or eimer_fuer(f"lexware:{kennung}")
        self._schlafen = schlafen or (lambda s: time.sleep(s))

    # ------------------------------------------------------------------ HTTP
    def _anfrage(
        self,
        methode: str,
        pfad: str,
        *,
        params: dict[str, Any] | None = None,
        daten: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        _pruefe_finalize(pfad, params)
        kopf = {"Authorization": f"Bearer {self._schluessel}", "Accept": accept}
        inhalt = None
        if daten is not None:
            kopf["Content-Type"] = "application/json"
            inhalt = als_json(daten).encode()
        letzter: ConnectorFehler | None = None
        for versuch in range(MAX_WIEDERHOLUNGEN + 1):
            self._eimer.nehmen()
            try:
                antwort = self._client.request(
                    methode, self.basis_url + pfad, params=params, content=inhalt, headers=kopf
                )
            except httpx.TransportError as fehler:
                letzter = NichtErreichbar(f"Netzwerkfehler: {type(fehler).__name__}")
            else:
                if antwort.status_code < 400:
                    return antwort
                letzter = self._fehler(antwort)
                if not letzter.wiederholbar:
                    raise letzter
            if versuch < MAX_WIEDERHOLUNGEN:
                self._schlafen(self._wartezeit(versuch, letzter))
        log.warning("Lexware-Anfrage endgültig fehlgeschlagen", extra={"pfad": pfad.split("?")[0]})
        assert letzter is not None
        raise letzter

    @staticmethod
    def _wartezeit(versuch: int, fehler: ConnectorFehler | None) -> float:
        basis = min(2.0**versuch, 30.0)
        retry_after = getattr(fehler, "retry_after", None)
        if retry_after:
            basis = max(basis, float(retry_after))
        return basis + random.uniform(0, basis * 0.25)  # noqa: S311 – Jitter, keine Kryptografie

    @staticmethod
    def _fehler(antwort: httpx.Response) -> ConnectorFehler:
        status = antwort.status_code
        try:
            text = antwort.text[:500]
        except Exception:
            text = ""
        fehler: ConnectorFehler
        if status == 429:
            fehler = RateLimitUeberschritten("HTTP 429", status)
            wert = antwort.headers.get("Retry-After", "")
            fehler.retry_after = float(wert) if wert.replace(".", "", 1).isdigit() else None  # type: ignore[attr-defined]
        elif status >= 500:
            fehler = NichtErreichbar(f"HTTP {status}", status)
        elif status in (401, 402, 403):
            fehler = NichtAutorisiert(f"HTTP {status}", status)
        elif status == 404:
            fehler = NichtGefunden(f"HTTP {status}", status)
        elif status == 409:
            fehler = Konflikt(f"HTTP {status}", status)
        else:
            fehler = Validierungsfehler(f"HTTP {status}: {text}", status)
        return fehler

    def _json(self, methode: str, pfad: str, **kwargs: Any) -> dict[str, Any]:
        antwort = self._anfrage(methode, pfad, **kwargs)
        daten: dict[str, Any] = antwort.json() if antwort.content else {}
        return daten

    def _seiten(self, pfad: str, params: dict[str, Any]) -> Iterator[dict[str, Any]]:
        seite = 0
        while True:
            daten = self._json("GET", pfad, params={**params, "page": seite, "size": SEITENGROESSE})
            yield from daten.get("content", [])
            if daten.get("last", True) or seite + 1 >= int(daten.get("totalPages", 0)):
                return
            seite += 1

    # ------------------------------------------------------------- Lesen
    def test(self) -> CompanyInfo:
        profil = self._json("GET", "/v1/profile")
        return CompanyInfo(
            organisation_id=str(profil.get("organizationId", "")),
            firmenname=str(profil.get("companyName", "")),
            verbindungs_id=str(profil.get("connectionId", "")),
            steuerart=str(profil.get("taxType") or "net"),
            kleinunternehmer=bool(profil.get("smallBusiness", False)),
        )

    @staticmethod
    def _receivable(eintrag: dict[str, Any]) -> Receivable:
        status: BelegStatus = _STATUS.get(eintrag.get("voucherStatus", ""), "offen")  # type: ignore[assignment]
        art: BelegArt = _ART.get(eintrag.get("voucherType", ""), "rechnung")  # type: ignore[assignment]
        offen_roh = eintrag.get("openAmount")
        if offen_roh is None:
            offen = (
                Decimal("0.00") if status in ("bezahlt", "storniert", "entwurf") else geld(eintrag.get("totalAmount"))
            )
        else:
            offen = geld(offen_roh)
        return Receivable(
            extern_id=str(eintrag["id"]),
            art=art,
            nummer=str(eintrag.get("voucherNumber") or ""),
            belegdatum=_datum(eintrag.get("voucherDate")),
            faellig_am=_datum(eintrag.get("dueDate")),
            kontakt_extern_id=eintrag.get("contactId"),
            kontakt_name=str(eintrag.get("contactName") or ""),
            brutto=geld(eintrag.get("totalAmount")),
            offen=offen,
            status=status,
            aktualisiert_extern=_zeit(eintrag.get("updatedDate")),
        )

    def list_receivables(self, status: str, updated_since: date | None = None) -> Iterable[Receivable]:
        """Rechnungen und Abschlagsrechnungen aus der Voucherlist; `status` z. B. "open", "overdue", "any"."""
        params: dict[str, Any] = {"voucherType": "invoice,downpaymentinvoice", "voucherStatus": status}
        if updated_since is not None:
            params["updatedDateFrom"] = updated_since.isoformat()
        for eintrag in self._seiten("/v1/voucherlist", params):
            yield self._receivable(eintrag)

    def list_open_receivables(self, updated_since: date | None = None) -> Iterable[Receivable]:
        # "overdue" darf laut Doku nicht mit anderen Status kombiniert werden: eigener Aufruf
        gesehen: set[str] = set()
        for status in ("open", "overdue"):
            for posten in self.list_receivables(status, updated_since):
                if posten.extern_id not in gesehen:
                    gesehen.add(posten.extern_id)
                    yield posten

    def list_open_quotations(self) -> Iterable[Receivable]:
        """Offene und angenommene Angebote (für den Abgleich Rechnung gegen Angebot, E10)."""
        params = {"voucherType": "quotation", "voucherStatus": "open,accepted"}
        for eintrag in self._seiten("/v1/voucherlist", params):
            posten = self._receivable({**eintrag, "voucherStatus": "open"})
            yield Receivable(**{**posten.__dict__, "art": "angebot", "offen": Decimal("0.00")})

    def get_quotation_positions(self, quotation_id: str) -> list[tuple[str, Decimal]]:
        """Artikel-IDs und Mengen eines Angebots; Positionen ohne Artikel werden übergangen."""
        angebot = self._json("GET", f"/v1/quotations/{quotation_id}")
        return [
            (str(p["id"]), Decimal(str(p.get("quantity") or 0)))
            for p in angebot.get("lineItems") or []
            if p.get("id") and p.get("type") in ("service", "material")
        ]

    def list_paid_receivables(self, updated_since: date) -> Iterable[Receivable]:
        yield from self.list_receivables("paid,paidoff", updated_since)

    def get_payment_status(self, voucher_id: str) -> PaymentStatus:
        try:
            daten = self._json("GET", f"/v1/payments/{voucher_id}")
        except Validierungsfehler as fehler:
            if fehler.status == 406:  # Entwurf: laut Doku kein Fehlerfall
                return PaymentStatus(offen=Decimal("0.00"), status="entwurf")
            raise
        status: BelegStatus = _STATUS.get(daten.get("voucherStatus", ""), "offen")  # type: ignore[assignment]
        zahlungen = tuple(
            (_datum(z.get("postingDate")), geld(z.get("amount"))) for z in daten.get("paymentItems", []) or []
        )
        return PaymentStatus(
            offen=geld(daten.get("openAmount")),
            status=status,
            bezahlt_am=_datum(daten.get("paidDate")),
            zahlungen=zahlungen,
        )

    def get_receivable(self, voucher_id: str) -> Receivable | None:
        """Einzelnen Beleg nachladen (Webhook): Rechnung bzw. Abschlagsrechnung plus Zahlstatus."""
        for art in ("invoice", "downpaymentinvoice"):
            try:
                beleg = self._json("GET", f"/v1/{_PFAD[art]}/{voucher_id}")
            except NichtGefunden:
                continue
            zahlung = self.get_payment_status(voucher_id) if beleg.get("voucherStatus") != "draft" else None
            adresse = beleg.get("address") or {}
            return self._receivable(
                {
                    "id": beleg.get("id", voucher_id),
                    "voucherType": art,
                    "voucherStatus": beleg.get("voucherStatus"),
                    "voucherNumber": beleg.get("voucherNumber"),
                    "voucherDate": beleg.get("voucherDate"),
                    "dueDate": beleg.get("dueDate"),
                    "contactId": adresse.get("contactId"),
                    "contactName": adresse.get("name"),
                    "totalAmount": (beleg.get("totalPrice") or {}).get("totalGrossAmount"),
                    "openAmount": str(zahlung.offen) if zahlung else None,
                    "updatedDate": beleg.get("updatedDate"),
                }
            )
        return None

    @staticmethod
    def _contact(daten: dict[str, Any]) -> Contact:
        firma = daten.get("company") or {}
        person = daten.get("person") or {}
        if firma:
            name = str(firma.get("name") or "")
        else:
            name = " ".join(p for p in (person.get("firstName"), person.get("lastName")) if p)
        mails = daten.get("emailAddresses") or {}
        email = ""
        for art in ("business", "office", "private", "other"):
            if mails.get(art):
                email = str(mails[art][0])
                break
        if not email:
            for ansprechpartner in firma.get("contactPersons") or []:
                if ansprechpartner.get("emailAddress"):
                    email = str(ansprechpartner["emailAddress"])
                    if ansprechpartner.get("primary"):
                        break
        kunde = (daten.get("roles") or {}).get("customer") or {}
        return Contact(
            extern_id=str(daten["id"]),
            name=name,
            email=email,
            kundennummer=str(kunde.get("number") or ""),
            ist_unternehmen=bool(firma) if (firma or person) else None,
            archiviert=bool(daten.get("archived", False)),
            adresse=LexwareConnector._adresse(daten),
        )

    @staticmethod
    def _adresse(daten: dict[str, Any]) -> str:
        """Erste Rechnungsadresse als mehrzeiliger Text (für Mahnschreiben der App)."""
        adressen = (daten.get("addresses") or {}).get("billing") or []
        if not adressen:
            return ""
        a = adressen[0]
        zeilen = [
            str(a.get("supplement") or ""),
            str(a.get("street") or ""),
            " ".join(x for x in (str(a.get("zip") or ""), str(a.get("city") or "")) if x),
        ]
        if a.get("countryCode") and a.get("countryCode") != "DE":
            zeilen.append(str(a["countryCode"]))
        return "\n".join(z for z in zeilen if z.strip())

    def create_contact(self, draft: ContactDraft) -> str:
        """Kunde anlegen (Doku: version 0, Rolle customer, company XOR person, je höchstens eine Adresse/E-Mail)."""
        daten: dict[str, Any] = {"version": 0, "roles": {"customer": {}}}
        if draft.ist_firma:
            daten["company"] = {"name": draft.name}
        else:
            person: dict[str, Any] = {"lastName": draft.name}
            if draft.vorname:
                person["firstName"] = draft.vorname
            daten["person"] = person
        if draft.strasse or draft.plz or draft.ort:
            daten["addresses"] = {
                "billing": [
                    {"street": draft.strasse, "zip": draft.plz, "city": draft.ort, "countryCode": draft.land or "DE"}
                ]
            }
        if draft.email:
            daten["emailAddresses"] = {"business": [draft.email]}
        if draft.telefon:
            daten["phoneNumbers"] = {"business": [draft.telefon]}
        if draft.notiz:
            daten["note"] = draft.notiz
        return str(self._json("POST", "/v1/contacts", daten=daten)["id"])

    def create_article(self, draft: ArticleDraft) -> str:
        """Artikel anlegen (Doku: title, type, unitName, price mit netPrice, leadingPrice NET, taxRate 0/7/19)."""
        daten: dict[str, Any] = {
            "title": draft.bezeichnung,
            "type": draft.typ,
            "unitName": draft.einheit,
            "price": {"netPrice": draft.netto, "leadingPrice": "NET", "taxRate": draft.steuersatz},
        }
        if draft.artikelnummer:
            daten["articleNumber"] = draft.artikelnummer
        return str(self._json("POST", "/v1/articles", daten=daten)["id"])

    def list_contacts(self) -> Iterable[Contact]:
        for eintrag in self._seiten("/v1/contacts", {"customer": "true"}):
            yield self._contact(eintrag)

    def get_contact(self, contact_id: str) -> Contact | None:
        try:
            return self._contact(self._json("GET", f"/v1/contacts/{contact_id}"))
        except NichtGefunden:
            return None

    def list_articles(self) -> Iterable[Article]:
        for eintrag in self._seiten("/v1/articles", {}):
            preis = eintrag.get("price") or {}
            netto = preis.get("netPrice")
            if netto is None and preis.get("grossPrice") is not None:
                satz = Decimal(str(preis.get("taxRate") or 0))
                netto = Decimal(str(preis["grossPrice"])) / (1 + satz / 100)
            yield Article(
                extern_id=str(eintrag["id"]),
                bezeichnung=str(eintrag.get("title") or ""),
                einheit=str(eintrag.get("unitName") or ""),
                netto=geld(netto),
                steuersatz=Decimal(str(preis.get("taxRate") or 0)),
                typ="SERVICE" if eintrag.get("type") == "SERVICE" else "PRODUCT",
                artikelnummer=str(eintrag.get("articleNumber") or ""),
                archiviert=bool(eintrag.get("archived", False)),
            )

    # ------------------------------------------------------------ Schreiben (nur Entwürfe)
    @staticmethod
    def _position(p: DraftLine, steuerart: str) -> dict[str, Any]:
        steuersatz = Decimal("0") if steuerart == "vatfree" else p.steuersatz
        preis: dict[str, Any] = {"currency": "EUR", "taxRatePercentage": steuersatz}
        if steuerart == "gross":
            preis["grossAmount"] = geld(p.netto * (1 + steuersatz / 100))
        else:
            preis["netAmount"] = p.netto
        position: dict[str, Any] = {
            "type": "custom",
            "name": p.name[:255],
            "quantity": p.menge,
            "unitName": p.einheit or "Stück",
            "unitPrice": preis,
        }
        if p.artikel_extern_id:
            position["type"] = "service" if p.artikel_typ == "SERVICE" else "material"
            position["id"] = p.artikel_extern_id
        if p.beschreibung:
            position["description"] = p.beschreibung
        return position

    def _deeplink(self, art: str, extern_id: str) -> str:
        return f"{APP_URL}/permalink/{_PFAD[art]}/edit/{extern_id}"

    def create_invoice_draft(self, draft: InvoiceDraft) -> ExternalRef:
        daten: dict[str, Any] = {
            "voucherDate": zeitpunkt(draft.belegdatum),
            "address": {"contactId": draft.kontakt_extern_id},
            "lineItems": [self._position(p, draft.steuerart) for p in draft.positionen],
            "totalPrice": {"currency": "EUR"},
            "taxConditions": {"taxType": draft.steuerart},
            "title": draft.titel,
        }
        if draft.leistung_von and draft.leistung_bis and draft.leistung_von != draft.leistung_bis:
            daten["shippingConditions"] = {
                "shippingType": "serviceperiod",
                "shippingDate": zeitpunkt(draft.leistung_von),
                "shippingEndDate": zeitpunkt(draft.leistung_bis),
            }
        elif draft.leistung_von or draft.leistung_bis:
            tag = draft.leistung_bis or draft.leistung_von
            assert tag is not None
            daten["shippingConditions"] = {"shippingType": "service", "shippingDate": zeitpunkt(tag)}
        else:
            daten["shippingConditions"] = {"shippingType": "none"}
        if draft.einleitung:
            daten["introduction"] = draft.einleitung
        if draft.bemerkung:
            daten["remark"] = draft.bemerkung
        antwort = self._json("POST", "/v1/invoices", daten=daten)  # ohne finalize: Entwurf
        return ExternalRef("invoice", str(antwort["id"]), self._deeplink("invoice", str(antwort["id"])))

    def create_quotation_draft(self, draft: QuotationDraft) -> ExternalRef:
        daten: dict[str, Any] = {
            "voucherDate": zeitpunkt(draft.belegdatum),
            "expirationDate": zeitpunkt(draft.gueltig_bis),
            "address": {"contactId": draft.kontakt_extern_id},
            "lineItems": [self._position(p, draft.steuerart) for p in draft.positionen],
            "totalPrice": {"currency": "EUR"},
            "taxConditions": {"taxType": draft.steuerart},
            "title": draft.titel,
        }
        if draft.einleitung:
            daten["introduction"] = draft.einleitung
        if draft.bemerkung:
            daten["remark"] = draft.bemerkung
        antwort = self._json("POST", "/v1/quotations", daten=daten)
        return ExternalRef("quotation", str(antwort["id"]), self._deeplink("quotation", str(antwort["id"])))

    def create_dunning_draft(self, invoice_id: str, fees: DunningFees) -> ExternalRef | None:
        """Mahnungsentwurf zur Rechnung. Steuerbedingungen und Kontakt müssen der Rechnung entsprechen (Doku)."""
        try:
            rechnung = self._json("GET", f"/v1/invoices/{invoice_id}")
        except NichtGefunden:  # Abschlagsrechnungen lassen sich laut Doku ebenfalls mahnen
            rechnung = self._json("GET", f"/v1/down-payment-invoices/{invoice_id}")
        adresse = rechnung.get("address") or {}
        if adresse.get("contactId"):
            empfaenger: dict[str, Any] = {"contactId": adresse["contactId"]}
        else:
            empfaenger = {"name": adresse.get("name", ""), "countryCode": adresse.get("countryCode", "DE")}
        steuer = rechnung.get("taxConditions") or {"taxType": "net"}
        brutto_preise = steuer.get("taxType") == "gross"

        def gebuehr(name: str, betrag: Decimal) -> dict[str, Any]:
            preis: dict[str, Any] = {"currency": "EUR", "taxRatePercentage": Decimal("0")}
            preis["grossAmount" if brutto_preise else "netAmount"] = betrag
            return {
                "type": "custom",
                "name": name,
                "quantity": Decimal("1"),
                "unitName": "pauschal",
                "unitPrice": preis,
            }

        positionen: list[dict[str, Any]] = [
            {
                "type": "text",
                "name": f"Offener Betrag aus Rechnung {fees.rechnungsnummer}: {_euro(fees.offen)}",
                "description": "Die Rechnung liegt diesem Schreiben bei bzw. ist Ihnen bereits zugegangen.",
            }
        ]
        if fees.zinsen > 0:
            positionen.append(gebuehr("Verzugszinsen (§ 288 BGB)", fees.zinsen))
            if fees.zinsen_text:
                positionen.append(
                    {"type": "text", "name": "Berechnung der Verzugszinsen", "description": fees.zinsen_text}
                )
        if fees.pauschale > 0:
            positionen.append(gebuehr("Verzugspauschale (§ 288 Abs. 5 BGB)", fees.pauschale))
        daten: dict[str, Any] = {
            "voucherDate": zeitpunkt(fees.belegdatum or datetime.now(BERLIN).date()),
            "address": empfaenger,
            "lineItems": positionen,
            "totalPrice": {"currency": "EUR"},
            "taxConditions": steuer,
            "shippingConditions": rechnung.get("shippingConditions") or {"shippingType": "none"},
            "title": "Mahnung" if fees.stufe <= 1 else f"{fees.stufe}. Mahnung",
        }
        if fees.einleitung:
            daten["introduction"] = fees.einleitung
        if fees.bemerkung:
            daten["remark"] = fees.bemerkung
        antwort = self._json("POST", "/v1/dunnings", params={"precedingSalesVoucherId": invoice_id}, daten=daten)
        return ExternalRef("dunning", str(antwort["id"]), self._deeplink("dunning", str(antwort["id"])))

    def get_pdf(self, ref: ExternalRef) -> bytes:
        antwort = self._anfrage("GET", f"/v1/{_PFAD[ref.art]}/{ref.extern_id}/file", accept="application/pdf")
        if not antwort.content.startswith(b"%PDF"):
            raise Validierungsfehler("Das Bestandstool hat kein PDF geliefert")
        return antwort.content

    # ------------------------------------------------------------ Webhooks
    def register_webhooks(self, callback_url: str) -> list[str]:
        ids = []
        for ereignis in WEBHOOK_EREIGNISSE:
            antwort = self._json(
                "POST", "/v1/event-subscriptions", daten={"eventType": ereignis, "callbackUrl": callback_url}
            )
            ids.append(str(antwort.get("subscriptionId") or antwort.get("id")))
        return ids

    def delete_webhooks(self, ids: Iterable[str]) -> None:
        for abo_id in ids:
            try:
                self._anfrage("DELETE", f"/v1/event-subscriptions/{abo_id}")
            except NichtGefunden:
                continue


def _euro(betrag: Decimal) -> str:
    text = f"{betrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"
