# Meilensteine und Tickets

Reihenfolge ist verbindlich. Ein Ticket ist fertig, wenn Code, Tests und die betroffene Vault-Seite aktuell sind und CI grün ist. Status hier pflegen: `[ ]` offen, `[x]` fertig. Aufwand in Personentagen (PT) für einen Entwickler, grob.

## M0 Gerüst (ca. 4 PT)

- [x] **M0-01** Django-Projekt `cockpit` mit Python 3.12, Django 5.2 LTS, Postgres 16, `uv`-Lockfile, Einstellungen über Umgebungsvariablen (`django-environ`), Apps laut `02-Architektur/Architektur.md` anlegen.
- [x] **M0-02** `docker-compose.yml` für lokal (web, worker, db) und `Dockerfile` (Non-Root). `make dev`, `make test`.
- [x] **M0-03** CI (GitHub Actions): ruff, mypy, pytest mit Postgres-Service, `makemigrations --check`.
- [x] **M0-04** Job-Queue `jobs`: Modell, `enqueue()`, Worker-Kommando mit `SKIP LOCKED`, Retries mit Backoff, Zeitplan (cron-artige Einträge in Code), SIGTERM-sauber, hängende Jobs nach Timeout freigeben. Tests.
- [ ] **M0-05** `audit`: Protokollmodell plus Postgres-Trigger gegen UPDATE/DELETE, Hilfsfunktion `protokolliere()`. Test, dass Update scheitert.
- [ ] **M0-06** Basis-Layout mit HTMX, mobile first, Footer mit Rechtstext-Platzhaltern (F5).

## M1 Konto, Lexware lesen, Cockpit (ca. 10 PT)

- [ ] **M1-01** `accounts`: Firma, Mitgliedschaft mit Rollen, Einladungscodes, Registrierung (A1), Login mit E-Mail.
- [ ] **M1-02** TOTP-2FA Pflicht mit Wiederherstellungscodes (A2). Bibliothek: `django-otp` oder eigene RFC-6238-Implementierung mit Replay-Schutz.
- [ ] **M1-03** Rate-Limits (A5) mit `django-ratelimit` je IP und je Konto.
- [ ] **M1-04** Mandantentrennung: `FirmaManager`, Middleware, generischer IDOR-Test (A4).
- [ ] **M1-05** `connectors`: Protokoll `AccountingConnector`, `LexwareConnector` mit Token-Bucket (2/s), Retry auf 429/5xx, Fehlerklassen. Tests mit aufgezeichneten Antworten.
- [ ] **M1-06** Verbindung anlegen, Schlüssel verschlüsselt speichern, Test-Aufruf (B1).
- [ ] **M1-07** Erstimport und nächtlicher Abgleich in den Spiegel (B2, B3 Teil Abgleich). Abnahme: Summen stimmen mit Lexware-Testkonto.
- [ ] **M1-08** Webhooks registrieren und empfangen, Signaturprüfung, idempotente Verarbeitung (B3).
- [ ] **M1-09** Cockpit-Startseite: Kennzahlen und Altersstruktur (C1), Liste offener Posten mit Filtern (C2), Kundenansicht (C3), Prognose 4 Wochen (C4), mobil (C5).
- [ ] **M1-10** Kundentyp pflegen: Liste "Kundentyp fehlt" mit Schnellauswahl Privat/Unternehmer (Voraussetzung für D3).

**Meilenstein-Abnahme M1:** Mit dem Lexware-Testkonto stimmen Summe offen, Summe überfällig und Anzahl exakt; eine in Lexware als bezahlt markierte Rechnung verschwindet binnen 5 Minuten aus "offen".

## M2 Mahnautomatik (ca. 10 PT)

- [ ] **M2-01** `dunning`: Mahnplan pro Firma mit Standardwerten (D1), Basiszins-Tabelle mit Startwerten als Data-Migration.
- [ ] **M2-02** Reine Funktionen `verzugsbeginn()`, `verzugszinsen()`, `pauschale()` mit Tabellen-Tests für jede Zeile aus `02-Architektur/Mahnlogik-und-Recht.md` (D4, D5).
- [ ] **M2-03** Täglicher Vorschlagslauf, idempotent, mit allen Vorbedingungen (D2, D3, D8).
- [ ] **M2-04** Freigabe-Ansicht: Liste, Einzel- und Sammelfreigabe, Verwerfen mit Grund, Vorschau der Mail (D6, D10).
- [ ] **M2-05** Versand-Job: Frische-Check (D9), Lexware-Mahnungsentwurf ab Stufe 1 und PDF (B6), Rechnungs-PDF für Stufe 0, E-Mail mit Anhang, Versand-Datensatz, Protokoll (D7). Fehler sichtbar mit Neuversuch.
- [ ] **M2-06** E-Mail-Versand: Plattform-SMTP (EU-Anbieter) mit Absendername und Reply-To der Firma; optional eigenes SMTP der Firma. Zustellfehler (Bounce) erfassen, soweit der Anbieter das meldet.
- [ ] **M2-07** Sammelfreigabe-Mail montags 7 Uhr mit Link ins Cockpit (Login nötig).
- [ ] **M2-08** Pausen für Kunde und Beleg (D8).

**Meilenstein-Abnahme M2:** Im Testkonto mit 20 präparierten Rechnungen (Mix Privat/Unternehmer, Teilzahlung, pausiert, bezahlt kurz vor Versand) entstehen exakt die erwarteten Vorschläge; nach Freigabe gehen die Mails an eine Test-Mailbox (Mailpit) mit korrekten Beträgen.

## M3 Erfassung per Sprache, Foto, Mail (ca. 10 PT)

- [ ] **M3-01** `capture`: Modelle, Upload und Browser-Aufnahme (E1), Dateilimits, Speicherung außerhalb des Webroots.
- [ ] **M3-02** Transkription mit Mistral (E3 Vorbereitung), Audio danach löschen (E8).
- [ ] **M3-03** Transkript-Vorschau und Bearbeiten (E3).
- [ ] **M3-04** Textaufbereitung: PDF-Text, CSV-Zeiterfassung (Eigenbau; `belegfluss/quellen.py` als Orientierung, Übernahme nur nach ADR-007), Mail-Parsing.
- [ ] **M3-05** Extraktion über Bedrock Frankfurt mit JSON-Schema, Bild-Input für Fotos, Stammdaten-Reduktion, Kostenlimit (E4, E9).
- [ ] **M3-06** Regel-Engine `capture/rules.py` (E4, E5, E10). Eigenbau gegen die Spiegel-Artikel; `belegfluss/regeln.py` als Orientierung, Übernahme nur nach ADR-007.
- [ ] **M3-07** Prüfansicht mit Herkunft, Hinweisen, Blockern, Bearbeiten (E6).
- [ ] **M3-08** Übertragung als Entwurf in Lexware (E7, B5). Test, dass nie `finalize` gesendet wird.
- [ ] **M3-09** Belegpostfach: IMAP-Abruf eines Sammelpostfachs mit Plus-Adressen je Firma (`belege+<token>@…`), Whitelist und DKIM/SPF-Prüfung über `Authentication-Results` (E2). IMAP mit Timeout, jede Firma isoliert.
- [ ] **M3-10** KI-Testfälle und Kommando `ki_testfaelle` (siehe KI-Pipeline).

## M4 Bericht, Onboarding, Härtung (ca. 8 PT)

- [ ] **M4-01** Wochenbericht (F1).
- [ ] **M4-02** Export je Firma (F3) mit CSV-Injection-Schutz.
- [ ] **M4-03** Onboarding-Assistent (F6).
- [ ] **M4-04** Löschjobs nach Fristen.
- [ ] **M4-05** Produktions-Compose mit Caddy, Backups mit restic, Restore-Probe-Skript, Health-Endpoint, Fehlererfassung (F4).
- [ ] **M4-06** Betriebshandbuch `vault/03-Umsetzung/Betriebshandbuch.md` schreiben (Deploy, Restore, Basiszins-Pflege, Schlüsselrotation, Störung Lexware).
- [ ] **M4-07** Prüfliste für das Team (nicht Code): Rechtstexte, AVV, Mahntexte und Zinslogik von Anwalt/Steuerberater prüfen lassen, IT-Haftpflicht.

**MVP-Abnahme:** siehe Definition of Done in `00-Start-hier.md`.

## M5 sevdesk (nach den ersten Pilotkunden)

- [ ] **M5-01** sevdesk-API-Doku prüfen (https://api.sevdesk.de/) und `SevdeskConnector` gegen das Protokoll implementieren; fehlende Fähigkeiten (z. B. Mahnungsentwurf) über `None` und eigenes Mahnschreiben-PDF abdecken.
- [ ] **M5-02** Cockpit und Mahnautomatik laufen unverändert gegen beide Adapter (G1).
