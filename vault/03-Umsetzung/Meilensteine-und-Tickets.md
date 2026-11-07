# Meilensteine und Tickets

Reihenfolge ist verbindlich. Ein Ticket ist fertig, wenn Code, Tests und die betroffene Vault-Seite aktuell sind und CI grün ist. Status hier pflegen: `[ ]` offen, `[x]` fertig. Aufwand in Personentagen (PT) für einen Entwickler, grob.

## M0 Gerüst (ca. 4 PT)

- [x] **M0-01** Django-Projekt `cockpit` mit Python 3.12, Django 5.2 LTS, Postgres 16, `uv`-Lockfile, Einstellungen über Umgebungsvariablen (`django-environ`), Apps laut `02-Architektur/Architektur.md` anlegen.
- [x] **M0-02** `docker-compose.yml` für lokal (web, worker, db) und `Dockerfile` (Non-Root). `make dev`, `make test`.
- [x] **M0-03** CI (GitHub Actions): ruff, mypy, pytest mit Postgres-Service, `makemigrations --check`.
- [x] **M0-04** Job-Queue `jobs`: Modell, `enqueue()`, Worker-Kommando mit `SKIP LOCKED`, Retries mit Backoff, Zeitplan (cron-artige Einträge in Code), SIGTERM-sauber, hängende Jobs nach Timeout freigeben. Tests.
- [x] **M0-05** `audit`: Protokollmodell plus Postgres-Trigger gegen UPDATE/DELETE, Hilfsfunktion `protokolliere()`. Test, dass Update scheitert.
- [x] **M0-06** Basis-Layout mit HTMX, mobile first, Footer mit Rechtstext-Platzhaltern (F5).

## M1 Konto, Lexware lesen, Cockpit (ca. 10 PT)

- [x] **M1-01** `accounts`: Firma, Mitgliedschaft mit Rollen, Einladungscodes, Registrierung (A1), Login mit E-Mail.
- [x] **M1-02** TOTP-2FA Pflicht mit Wiederherstellungscodes (A2). Bibliothek: `django-otp` oder eigene RFC-6238-Implementierung mit Replay-Schutz.
- [x] **M1-03** Rate-Limits (A5) mit `django-ratelimit` je IP und je Konto.
- [x] **M1-04** Mandantentrennung: `FirmaManager`, Middleware, generischer IDOR-Test (A4).
- [x] **M1-05** `connectors`: Protokoll `AccountingConnector`, `LexwareConnector` mit Token-Bucket (2/s), Retry auf 429/5xx, Fehlerklassen. Tests mit aufgezeichneten Antworten.
- [x] **M1-06** Verbindung anlegen, Schlüssel verschlüsselt speichern, Test-Aufruf (B1).
- [x] **M1-07** Erstimport und nächtlicher Abgleich in den Spiegel (B2, B3 Teil Abgleich). Abnahme: Summen stimmen mit Lexware-Testkonto.
- [x] **M1-08** Webhooks registrieren und empfangen, Signaturprüfung, idempotente Verarbeitung (B3).
- [x] **M1-09** Cockpit-Startseite: Kennzahlen und Altersstruktur (C1), Liste offener Posten mit Filtern (C2), Kundenansicht (C3), Prognose 4 Wochen (C4), mobil (C5).
- [x] **M1-10** Kundentyp pflegen: Liste "Kundentyp fehlt" mit Schnellauswahl Privat/Unternehmer (Voraussetzung für D3).

**Meilenstein-Abnahme M1:** Mit dem Lexware-Testkonto stimmen Summe offen, Summe überfällig und Anzahl exakt; eine in Lexware als bezahlt markierte Rechnung verschwindet binnen 5 Minuten aus "offen".

## M2 Mahnautomatik (ca. 10 PT)

- [x] **M2-01** `dunning`: Mahnplan pro Firma mit Standardwerten (D1), Basiszins-Tabelle mit Startwerten als Data-Migration.
- [x] **M2-02** Reine Funktionen `verzugsbeginn()`, `verzugszinsen()`, `pauschale()` mit Tabellen-Tests für jede Zeile aus `02-Architektur/Mahnlogik-und-Recht.md` (D4, D5).
- [x] **M2-03** Täglicher Vorschlagslauf, idempotent, mit allen Vorbedingungen (D2, D3, D8).
- [x] **M2-04** Freigabe-Ansicht: Liste, Einzel- und Sammelfreigabe, Verwerfen mit Grund, Vorschau der Mail (D6, D10).
- [x] **M2-05** Versand-Job: Frische-Check (D9), Lexware-Mahnungsentwurf ab Stufe 1 und PDF (B6), Rechnungs-PDF für Stufe 0, E-Mail mit Anhang, Versand-Datensatz, Protokoll (D7). Fehler sichtbar mit Neuversuch.
- [x] **M2-06** E-Mail-Versand: Plattform-SMTP (EU-Anbieter) mit Absendername und Reply-To der Firma; optional eigenes SMTP der Firma. Zustellfehler (Bounce) erfassen, soweit der Anbieter das meldet.
- [x] **M2-07** Sammelfreigabe-Mail montags 7 Uhr mit Link ins Cockpit (Login nötig).
- [x] **M2-08** Pausen für Kunde und Beleg (D8).

**Meilenstein-Abnahme M2:** Im Testkonto mit 20 präparierten Rechnungen (Mix Privat/Unternehmer, Teilzahlung, pausiert, bezahlt kurz vor Versand) entstehen exakt die erwarteten Vorschläge; nach Freigabe gehen die Mails an eine Test-Mailbox (Mailpit) mit korrekten Beträgen.

## M3 Erfassung per Sprache, Foto, Mail (ca. 10 PT)

- [x] **M3-01** `capture`: Modelle, Upload und Browser-Aufnahme (E1), Dateilimits, Speicherung außerhalb des Webroots.
- [x] **M3-02** Transkription mit Mistral (E3 Vorbereitung), Audio danach löschen (E8).
- [x] **M3-03** Transkript-Vorschau und Bearbeiten (E3).
- [x] **M3-04** Textaufbereitung: PDF-Text, CSV-Zeiterfassung (Eigenbau; `belegfluss/quellen.py` als Orientierung, Übernahme nur nach ADR-007), Mail-Parsing.
- [x] **M3-05** Extraktion über Bedrock Frankfurt mit JSON-Schema, Bild-Input für Fotos, Stammdaten-Reduktion, Kostenlimit (E4, E9).
- [x] **M3-06** Regel-Engine `capture/rules.py` (E4, E5, E10). Eigenbau gegen die Spiegel-Artikel; `belegfluss/regeln.py` als Orientierung, Übernahme nur nach ADR-007.
- [x] **M3-07** Prüfansicht mit Herkunft, Hinweisen, Blockern, Bearbeiten (E6).
- [x] **M3-08** Übertragung als Entwurf in Lexware (E7, B5). Test, dass nie `finalize` gesendet wird.
- [x] **M3-09** Belegpostfach: IMAP-Abruf eines Sammelpostfachs mit Plus-Adressen je Firma (`belege+<token>@…`), Whitelist und DKIM/SPF-Prüfung über `Authentication-Results` (E2). IMAP mit Timeout, jede Firma isoliert.
- [x] **M3-10** KI-Testfälle und Kommando `ki_testfaelle` (siehe KI-Pipeline).

## M4 Bericht, Onboarding, Härtung (ca. 8 PT)

- [x] **M4-01** Wochenbericht (F1).
- [x] **M4-02** Export je Firma (F3) mit CSV-Injection-Schutz.
- [x] **M4-03** Onboarding-Assistent (F6).
- [x] **M4-04** Löschjobs nach Fristen.
- [x] **M4-05** Produktions-Compose mit Caddy, Backups mit restic, Restore-Probe-Skript, Health-Endpoint, Fehlererfassung (F4).
- [x] **M4-06** Betriebshandbuch `vault/03-Umsetzung/Betriebshandbuch.md` schreiben (Deploy, Restore, Basiszins-Pflege, Schlüsselrotation, Störung Lexware).
- [x] **M4-07** Prüfliste für das Team (nicht Code): Rechtstexte, AVV, Mahntexte und Zinslogik von Anwalt/Steuerberater prüfen lassen, IT-Haftpflicht. Liste in `vault/03-Umsetzung/Pruefliste-Team.md`; die Prüfungen selbst sind Aufgabe des Teams und offen.

**MVP-Abnahme:** siehe Definition of Done in `00-Start-hier.md`.

## M5 sevdesk (nach den ersten Pilotkunden)

- [ ] **M5-01** sevdesk-API-Doku prüfen (https://api.sevdesk.de/) und `SevdeskConnector` gegen das Protokoll implementieren; fehlende Fähigkeiten (z. B. Mahnungsentwurf) über `None` und eigenes Mahnschreiben-PDF abdecken.
- [ ] **M5-02** Cockpit und Mahnautomatik laufen unverändert gegen beide Adapter (G1).

## M6 Import aus Excel (vor dem Pilot, Priorität vor M5)

Grundlage: ADR-008, Anforderungen H1–H9. Entschieden am 5. November 2026.

- [x] **M6-01** Spezifikation, ADR-008, Tickets, Datenmodell (H1–H9).
- [x] **M6-02** Excel und CSV einlesen: Tabellenblatt, Kopfzeile, deutsche Zahlen und Daten, Schutz vor übergroßen Dateien (H1).
- [x] **M6-03** Spaltenzuordnung mit Vorschlägen und Vorlagen zum Herunterladen (H2).
- [x] **M6-04** Kunden-Import nach Lexware mit Vorschau, Dubletten, Freigabe, Job und Protokoll; Kundentyp nur nach Bestätigung (H3, H4, H9).
- [x] **M6-05** Artikel-Import nach Lexware mit Vorschau, Dubletten, Freigabe, Job und Protokoll (H3, H5, H9).
- [x] **M6-06** Offene Posten aus Excel nur im Cockpit, vom Lexware-Abgleich ausgenommen, Zahlstatus von Hand (H6, H7).
- [x] **M6-07** Mahnwesen für importierte Posten: Versand mit Zahlstatus aus dem Cockpit, Mahnschreiben-PDF der App, Hinweis in der Freigabe (H8).
- [x] **M6-08** Oberfläche (Upload, Zuordnung, Vorschau, Freigabe, Ergebnis), Hinweis im Einrichtungs-Assistenten, Tests, Vault.

## M7 Rückmeldung Lukas (nach M6, vor dem Pilot)

Rückmeldung von Lukas, Umfang am 5. November 2026 von Yannick entschieden: Die schnellen Punkte werden gebaut, die großen als Konzept festgehalten.

- [x] **M7-01** Spezifikation (I1–I7), ADR-009, Konzept für Abo-Verwaltung, Team-Chat, KI-Hilfe-Chat und KI-Telefonassistent.
- [x] **M7-02** Angebote im Spiegel: Ablaufdatum, Status „angenommen“ und „abgelehnt“, Abgleich der letzten 12 Monate.
- [x] **M7-03** „Angebote & Rechnungen“ statt „Erfassen“; Cockpit mit Reitern Überblick, Rechnungen, Angebote, Mahnungen (I1, I2).
- [x] **M7-04** Statistik Woche und Monat inklusive Angebote (I3).
- [x] **M7-05** Angebots-Erinnerung an den Endkunden nach Freigabe (I4, ADR-009).
- [x] **M7-06** Profil-Menü mit Avataren (I5).
- [x] **M7-07** Hinweis zur E-Rechnung (I6).

## M8 KI-Telefonassistent (Prototyp, nach M7)

Wunsch von Lukas, Entscheidung von Yannick am 5. November 2026: Live-Gespräch, im Pilot für alle einschaltbar. Echte Anrufe erst nach SIP-Trunk, Asterisk-Installation und rechtlicher Prüfung (ADR-010).

- [x] **M8-01** Spezifikation J1–J8, ADR-010, Tickets.
- [x] **M8-02** Modelle und Gesprächsführung mit Pflichtansage, Grenzen, Ausfallbetrieb und Rückruf-Notiz (J1–J4).
- [x] **M8-03** Rückruf-Notizen, Einstellungen, Benachrichtigung, Navigation, Löschfristen (J5, J8).
- [x] **M8-04** Testanruf im Browser (J6).
- [x] **M8-05** Telefonie: Anmeldung durch Asterisk, AudioSocket-Dienst, Spracherkennung und Sprachausgabe, Betriebshandbuch (J7).
- [x] **M8-06** Kostenkalkulation Telefonassistent ([[Kostenkalkulation-Telefonassistent]]), Sprachausgabe Voxtral statt Piper-„thorsten“, eigenes Telefon-Limit, Vault.

## M9 Rechnungskopien und Kontoauszüge (ADR-011 Stufe 3, nach M8)

Entschieden von Yannick am 6. November 2026. Ziel: Betriebe mit jedem Rechnungsprogramm (auch DATEV) und ohne Lexware können Belegfluss nutzen.

- [x] **M9-01** Spezifikation K1–K10, ADR-011 angenommen, Tickets.
- [x] **M9-02** E-Rechnung lesen: ZUGFeRD/Factur-X, XRechnung CII und UBL (K2).
- [x] **M9-03** Kopie-Adresse und Hochladen, Posten und Kunden ohne Lexware, Gutschriften, Dubletten, Mahnwesen auch ohne Lexware-Verbindung (K1, K3, K4, K8).
- [x] **M9-04** PDF ohne E-Rechnung: KI liest vor, Mensch bestätigt (K5).
- [x] **M9-05** Kontoauszug camt.053/camt.052 und CSV, nur Gutschriften (K6).
- [x] **M9-06** Zahlungen zuordnen und bestätigen, Hinweis auf den letzten Kontoauszug in der Freigabe (K7, K8).
- [x] **M9-07** Oberfläche, Einrichtung, Löschfristen, IDOR, Demo-Daten, Vault (K9, K10).
- [x] **M9-08** Excel-Import ohne Lexware: Kunden nur in Belegfluss, offene Rechnungen legen fehlende Kunden an, Artikel nur mit Lexware (H10, ADR-008 Nachtrag).
- [x] **M9-09** Positionsliste zum Abtippen: Belegerfassung ohne Lexware endet mit einer als Entwurf markierten Liste (Ansicht, CSV), ohne Nummer, Preise nur vom Menschen (K11, ADR-011 Stufe 1).
