"""Demo-Connector für die lokale Ansicht (`manage.py demo_daten`), nur mit DJANGO_DEBUG=true.

Arbeitet ausschließlich auf dem Spiegel in der eigenen Datenbank und schickt keine einzige Anfrage nach
außen. Entwürfe und Mahnungen „anzulegen“ heißt hier: eine Demo-ID vergeben und ein als Demo gekennzeichnetes
PDF liefern. In Produktion (DEBUG aus) wird er nie verwendet.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from accounts.models import Firma
from ledger.models import Artikel, Beleg, Kontakt

from .base import (
    Article,
    ArticleDraft,
    CompanyInfo,
    Contact,
    ContactDraft,
    DunningFees,
    ExternalRef,
    InvoiceDraft,
    PaymentStatus,
    QuotationDraft,
    Receivable,
)

DEMO_ORGANISATION = "demo-ohne-lexware"


def demo_pdf(titel: str) -> bytes:
    """Kleines gültiges PDF mit einem Hinweistext (ohne Zusatzbibliothek)."""
    text = titel.encode("latin-1", "replace").replace(b"(", b"[").replace(b")", b"]")
    inhalt = b"BT /F1 14 Tf 50 780 Td (" + text + b") Tj 0 -24 Td (Demo - kein Dokument aus Lexware) Tj ET"
    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = b"%PDF-1.4\n"
    versatz = []
    for nummer, objekt in enumerate(objekte, start=1):
        versatz.append(len(pdf))
        pdf += f"{nummer} 0 obj\n".encode() + objekt + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objekte) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{v:010d} 00000 n \n".encode() for v in versatz)
    pdf += f"trailer\n<< /Size {len(objekte) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return pdf


class DemoConnector:
    def __init__(self, firma: Firma) -> None:
        self.firma = firma

    def _posten(self, beleg: Beleg) -> Receivable:
        return Receivable(
            extern_id=beleg.extern_id,
            art=beleg.art,  # type: ignore[arg-type]
            nummer=beleg.nummer,
            belegdatum=beleg.belegdatum,
            faellig_am=beleg.faellig_am,
            kontakt_extern_id=beleg.kontakt.extern_id if beleg.kontakt else None,
            kontakt_name=beleg.kontakt_name,
            brutto=beleg.brutto,
            offen=beleg.offen,
            status=beleg.status,  # type: ignore[arg-type]
        )

    def _belege(self) -> Iterable[Beleg]:
        return Beleg.objects.fuer(self.firma).select_related("kontakt")

    def test(self) -> CompanyInfo:
        return CompanyInfo(organisation_id=DEMO_ORGANISATION, firmenname=self.firma.name)

    def list_open_receivables(self, updated_since: date | None = None) -> Iterable[Receivable]:
        return [
            self._posten(b)
            for b in self._belege()
            if b.status in Beleg.OFFENE_STATUS and b.art in (Beleg.Art.RECHNUNG, Beleg.Art.ABSCHLAG)
        ]

    def list_receivables(self, status: str, updated_since: date | None = None) -> Iterable[Receivable]:
        return []

    def get_receivable(self, voucher_id: str) -> Receivable | None:
        beleg = Beleg.objects.fuer(self.firma).select_related("kontakt").filter(extern_id=voucher_id).first()
        return self._posten(beleg) if beleg else None

    def get_payment_status(self, voucher_id: str) -> PaymentStatus:
        beleg = Beleg.objects.fuer(self.firma).get(extern_id=voucher_id)
        return PaymentStatus(offen=beleg.offen, status=beleg.status, bezahlt_am=beleg.bezahlt_am)

    def list_contacts(self) -> Iterable[Contact]:
        return [
            Contact(k.extern_id, k.name, k.email, k.kundennummer, k.ist_unternehmen_extern, k.archiviert, k.adresse)
            for k in Kontakt.objects.fuer(self.firma)
        ]

    def get_contact(self, contact_id: str) -> Contact | None:
        return next((c for c in self.list_contacts() if c.extern_id == contact_id), None)

    def list_articles(self) -> Iterable[Article]:
        return [
            Article(a.extern_id, a.bezeichnung, a.einheit, a.netto, a.steuersatz, a.typ, a.artikelnummer, a.archiviert)
            for a in Artikel.objects.fuer(self.firma)
        ]

    def create_contact(self, draft: ContactDraft) -> str:
        extern_id = f"demo-kontakt-{uuid.uuid4().hex[:8]}"
        adresse = "\n".join(z for z in (draft.strasse, f"{draft.plz} {draft.ort}".strip()) if z)
        Kontakt.objects.create(
            firma=self.firma,
            extern_id=extern_id,
            name=" ".join(x for x in (draft.vorname, draft.name) if x),
            email=draft.email,
            ist_unternehmen_extern=draft.ist_firma,
            adresse=adresse,
        )
        return extern_id

    def create_article(self, draft: ArticleDraft) -> str:
        extern_id = f"demo-artikel-{uuid.uuid4().hex[:8]}"
        Artikel.objects.create(
            firma=self.firma,
            extern_id=extern_id,
            bezeichnung=draft.bezeichnung,
            einheit=draft.einheit,
            netto=draft.netto,
            steuersatz=draft.steuersatz,
            typ=draft.typ,
            artikelnummer=draft.artikelnummer,
        )
        return extern_id

    def create_invoice_draft(self, draft: InvoiceDraft) -> ExternalRef:
        return ExternalRef("invoice", f"demo-rechnung-{uuid.uuid4().hex[:8]}")

    def create_quotation_draft(self, draft: QuotationDraft) -> ExternalRef:
        return ExternalRef("quotation", f"demo-angebot-{uuid.uuid4().hex[:8]}")

    def create_dunning_draft(self, invoice_id: str, fees: DunningFees) -> ExternalRef | None:
        return ExternalRef("dunning", f"demo-mahnung-{uuid.uuid4().hex[:8]}")

    def get_pdf(self, ref: ExternalRef) -> bytes:
        titel = {"dunning": "Mahnung", "invoice": "Rechnung", "downpaymentinvoice": "Abschlagsrechnung"}.get(
            ref.art, "Beleg"
        )
        return demo_pdf(f"{titel} {ref.extern_id}")

    def list_open_quotations(self) -> Iterable[Receivable]:
        return [
            self._posten(b) for b in self._belege() if b.art == Beleg.Art.ANGEBOT and b.status in Beleg.OFFENE_STATUS
        ]

    def get_quotation_positions(self, quotation_id: str) -> list[tuple[str, Decimal]]:
        return []

    def register_webhooks(self, callback_url: str) -> list[str]:
        return []

    def delete_webhooks(self, ids: Iterable[str]) -> None:
        return None
