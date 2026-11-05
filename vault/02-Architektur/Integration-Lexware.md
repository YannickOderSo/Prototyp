# Integration Lexware Office

Offizielle Doku: https://developers.lexware.io/docs/ — vor jeder Implementierung den jeweiligen Abschnitt erneut lesen. Stand der Prüfung: 5. November 2026.

## Grundlagen (verifiziert)

- Basis-URL `https://api.lexware.io`, Header `Authorization: Bearer {apiKey}`. Schlüssel erzeugt der Kunde unter https://app.lexware.de/addons/public-api. Die Public API erfordert den Tarif **XL**.
- **Rate-Limit: 2 Anfragen pro Sekunde** über alle Endpunkte; bei Überschreitung HTTP 429 ohne Ausführung. Token-Bucket je Verbindung, Retry mit exponentiellem Backoff und Jitter.

## Endpunkte, die wir nutzen

| Zweck | Aufruf (verifiziert) | Hinweis |
| --- | --- | --- |
| Offene Posten listen | `GET /v1/voucherlist?voucherType=invoice,downpaymentinvoice&voucherStatus=open&page=0&size=250` | `voucherType` und `voucherStatus` sind Pflicht. `overdue` darf nicht mit anderen Status kombiniert werden, also eigener Aufruf. Max. 250 je Seite, max. 10.000 Einträge. Felder: id, voucherType, voucherStatus, voucherNumber, voucherDate, dueDate, contactId, contactName, totalAmount, openAmount, currency, updatedDate |
| Inkrementell | gleicher Aufruf mit `updatedDateFrom=yyyy-MM-dd` | für nächtlichen Abgleich |
| Bezahlt-Status | `GET /v1/payments/{voucherId}` | Felder openAmount, paymentStatus, paidDate, paymentItems |
| Rechnung lesen | `GET /v1/invoices/{id}` | voucherStatus: draft, open, paid, voided |
| Rechnungsentwurf | `POST /v1/invoices` **ohne** `finalize` | ohne `finalize` entsteht ein Entwurf. `finalize=true` ist in der App verboten (Linter-Regel / Test) |
| Angebotsentwurf | `POST /v1/quotations` ohne `finalize` | wie oben |
| Mahnungsentwurf | `POST /v1/dunnings?precedingSalesVoucherId={invoiceId}` | Mahnungen entstehen immer als Entwurf. Pflichtfelder laut Doku (geprüft 5. November 2026): voucherDate, address, lineItems, taxConditions, shippingConditions, totalPrice. Kontakt und Steuerbedingungen müssen der Rechnung entsprechen; die App lädt dafür vorher `GET /v1/invoices/{id}`. Positionen: Textposition mit offenem Betrag, Zinsen und Pauschale als `custom` mit 0 % USt (wie im Doku-Beispiel bei `taxType net`) |
| Mahnungs-PDF | `GET /v1/dunnings/{id}/file` | `/document` ist veraltet |
| Rechnungs-PDF | `GET /v1/invoices/{id}/file` | Anhang für Erinnerung (Stufe 0) |
| Kontakte | `GET /v1/contacts?page=…`, `GET /v1/contacts/{id}` | Filter email, name, number, customer |
| Artikel | `GET /v1/articles?page=…` | Filter type `SERVICE` / `PRODUCT` |
| Webhooks | `POST/GET/DELETE /v1/event-subscriptions` | Events: `invoice.created`, `invoice.changed`, `invoice.status.changed`, `invoice.deleted`, `payment.changed`, `down-payment-invoice.status.changed`, `contact.changed`, `contact.created`, `article.changed`, `dunning.created`, `token.revoked` |

## Wichtige Einschränkung (verifiziert)

Die API beschreibt **keinen E-Mail-Versand** von Rechnungen oder Mahnungen. Die App versendet Erinnerungen und Mahnungen daher selbst per E-Mail mit dem PDF aus Lexware als Anhang. Das ist zugleich der Kernnutzen gegenüber Lexware selbst.

## Webhooks

- Endpunkt `POST /hooks/lexware/{verbindung_token}`. Signaturprüfung laut Lexware-Doku (geprüft 5. November 2026): Header `X-Lxo-Signature` enthält eine base64-kodierte RSA-SHA512-Signatur des JSON-Bodys; öffentlicher Schlüssel unter https://developers.lexware.io/webhookSignature/public/public_key.pub (Kopie in `tests/fixtures/lexware/webhook_public_key.pub` und im Code).
- Payload: `organizationId`, `eventType`, `resourceId`, `eventDate`. `POST /v1/event-subscriptions` antwortet mit `id` (Abo-ID). Lexware erwartet binnen 5000 ms 200/201/202/204, sonst Wiederholungen; 404 oder 410 löschen das Abo. Daher: sofort quittieren, Arbeit in die Job-Queue.
- Webhook-Payload enthält nur die Resource-ID: immer nachladen, nie dem Payload vertrauen.
- Idempotent verarbeiten; `token.revoked` setzt die Verbindung auf "getrennt" und benachrichtigt den Inhaber.

## Abgleich-Strategie

1. Erstimport: voucherlist `open` und separat `overdue`, dann Kontakte und Artikel, dann für jede offene Rechnung `payments`.
2. Laufend: Webhooks.
3. Nachts 2 Uhr: voucherlist mit `updatedDateFrom` = letzter Abgleich minus 1 Tag. Zusätzlich jede in der App als offen geführte Rechnung, die nicht mehr in der Offen-Liste auftaucht, einzeln nachladen.
4. Vor jedem Versand einer Mahnung: `GET /v1/payments/{id}` (Frische-Check, D9).

## Umsetzung (M1-05)

- `connectors/base.py`: Protokoll `AccountingConnector` und Datentypen (alle Beträge `Decimal`, Daten in Europe/Berlin). Ergänzt gegenüber dem Entwurf unten: `list_receivables(status, updated_since)` (für den nächtlichen Abgleich mit `voucherStatus=any`), `get_receivable(id)` (Webhook-Nachladen), `get_contact(id)`, `delete_webhooks(ids)`.
- `connectors/lexware.py`: Token-Bucket je Verbindung (2/s, keine Bursts, also mindestens 0,5 s Abstand), bis zu 5 Wiederholungen bei 429, 5xx und Netzwerkfehlern mit exponentiellem Backoff, Jitter und `Retry-After`. 401/402/403 → `NichtAutorisiert`, 404 → `NichtGefunden`, 4xx → `Validierungsfehler`. `GET /v1/payments` mit 406 (Entwurf) ist laut Doku kein Fehler.
- `finalize`: `_anfrage()` verweigert jede Anfrage mit `finalize` in Pfad oder Parametern; ein Test prüft alle Requests aller schreibenden Methoden, ein zweiter durchsucht den Quelltext.
- Geld wird ohne float geschrieben (`als_json`: Decimal als JSON-Zahl).
- Tests laufen gegen **nachgebaute** Antworten im Doku-Format (`tests/fixtures/lexware/`), nicht gegen ein echtes Konto.

## Adapter-Schnittstelle (für sevdesk später)

```python
class AccountingConnector(Protocol):
    def test(self) -> CompanyInfo: ...
    def list_open_receivables(self, updated_since: date | None) -> Iterable[Receivable]: ...
    def get_payment_status(self, voucher_id: str) -> PaymentStatus: ...
    def list_contacts(self) -> Iterable[Contact]: ...
    def list_articles(self) -> Iterable[Article]: ...
    def create_invoice_draft(self, draft: InvoiceDraft) -> ExternalRef: ...
    def create_quotation_draft(self, draft: QuotationDraft) -> ExternalRef: ...
    def create_dunning_draft(self, invoice_id: str, fees: DunningFees) -> ExternalRef | None: ...
    def get_pdf(self, ref: ExternalRef) -> bytes: ...
    def register_webhooks(self, callback_url: str) -> list[str]: ...
```

`create_dunning_draft` darf `None` liefern, wenn das Bestandstool keine Mahnungen per API kennt; dann erzeugt die App ein eigenes Mahnschreiben-PDF (nur Zahlungsaufforderung, kein Steuerbeleg).

## Testkonto

Ein eigenes Lexware-Office-XL-Testkonto mit separater E-Mail-Adresse. Nie gegen ein Konto mit echten Rechnungen entwickeln. Für Unit-Tests aufgezeichnete Antworten (VCR-Kassetten) unter `tests/fixtures/lexware/`.
