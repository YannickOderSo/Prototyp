# Architektur

## Überblick

Ein Django-Monolith mit Postgres und einem Hintergrund-Worker. Server-gerenderte Oberfläche mit HTMX. Das Bestandstool (Lexware Office) ist das System of Record für Kunden, Artikel, Rechnungen, Zahlungen und Mahnungsdokumente. Die App hält einen **Spiegel** davon plus eigene Daten (Mahnplan, Vorschläge, Freigaben, Versände, Erfassungen, Protokoll).

```mermaid
flowchart LR
  subgraph Kunde
    U[Inhaber / Bürokraft<br>Browser, Handy]
    M[Mail-Weiterleitung]
  end
  subgraph App[Cockpit auf Hetzner DE]
    W[Django Web<br>HTMX-Oberfläche]
    Q[(Postgres)]
    K[Worker<br>Jobs + Zeitplan]
    IN[IMAP-Abruf<br>Belegpostfach]
  end
  subgraph Extern[EU-Dienste]
    LX[Lexware Office API]
    STT[Mistral Voxtral EU]
    LLM[Claude via Bedrock Frankfurt]
    SMTP[EU-SMTP-Versand]
  end
  U --> W
  M --> IN --> Q
  W <--> Q
  K <--> Q
  K <--> LX
  LX -- Webhooks --> W
  K --> STT
  K --> LLM
  K --> SMTP
```

## Komponenten

| Komponente | Verantwortung |
| --- | --- |
| `accounts` | Nutzer, Firma, Mitgliedschaft, Rollen, 2FA, Einladungscodes, Rate-Limits |
| `connectors` | Adapter-Schnittstelle `AccountingConnector` plus `LexwareConnector` (später `SevdeskConnector`); Rate-Limit, Retry, Webhook-Empfang, Abgleich |
| `ledger` | Spiegel: Kontakt, Artikel, Beleg (Rechnung/Angebot), Zahlstatus; Altersstruktur, Prognose |
| `dunning` | Mahnplan, Regel-Engine (Verzug, Zinsen, Pauschale), täglicher Vorschlagslauf, Freigabe, Versand |
| `capture` | Erfassung: Upload, Aufnahme, Belegpostfach, Transkription, Extraktion, Regeln, Prüfansicht, Entwurf ins Bestandstool |
| `reports` | Wochenbericht, Export |
| `audit` | Append-only-Protokoll |
| `jobs` | Postgres-basierte Job-Queue (`SELECT … FOR UPDATE SKIP LOCKED`), Zeitplan, Wiederholungen |
| `web` | Seiten, Templates, HTMX-Partials, Rechtstexte |

## Abläufe

1. **Verbinden:** Inhaber gibt Lexware-Schlüssel ein → Testaufruf → Job `initial_sync` → Webhooks registrieren.
2. **Abgleich:** Webhook trifft ein → Signatur prüfen → Job `sync_voucher(id)` → Spiegel aktualisieren. Nachts `full_sync` über `voucherlist`.
3. **Mahnen:** Täglich 5 Uhr `dunning_proposals` je Firma → Vorschläge. Montag 7 Uhr Sammelmail. Freigabe → Job `send_dunning(proposal)` → Frische-Check → ggf. Lexware-Mahnungsentwurf → PDF → Mail → Protokoll.
4. **Erfassen:** Upload/Aufnahme/Mail → `Capture` → Job `transcribe` → Job `extract` → Regeln → Prüfansicht → Freigabe → Job `push_draft` → Lexware-Entwurf → Protokoll.

## Warum ein Monolith

Ein Entwickler, ein Server, wenige hundert Kunden im ersten Jahr. Microservices würden nur Betriebslast erzeugen. Die Adapter-Schnittstelle trennt das Bestandstool sauber, das genügt.
