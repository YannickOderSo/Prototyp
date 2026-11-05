# Fortschritt

Laufender Stand der Umsetzung. Nach jedem Meilenstein folgt ein Bericht. Grundsatz: Was nur gegen
Mocks oder nachgebaute HTTP-Antworten getestet ist, steht ausdrücklich so da. Nichts hier
behauptet einen Echtlauf gegen Lexware, Mistral, Bedrock oder einen SMTP-Anbieter, solange er nicht stattgefunden hat.

## Belegfluss: übernommen oder bewusst neu gebaut

Regeln: ADR-007. Übernommene Stellen tragen im Code den Vermerk
`Angelehnt an belegfluss/<datei>.py (Lukas Welker, Nutzung freigegeben am 2026-11-05)`.

| Bereich | Entscheidung | Begründung |
| --- | --- | --- |
| Projektstruktur, Einstellungen, Nutzermodell | neu gebaut | Eigene Struktur nach Vault; Belegfluss hat zwei Architekturen (CLI-Bot und Web), die wir nicht wiederholen |
| Job-Queue und Worker | neu gebaut | ADR-007 verbietet den Belegfluss-Worker-Loop; eigene Postgres-Queue mit SKIP LOCKED, Zeitlimit und Backoff |
| Protokoll | neu gebaut | Belegfluss hat kein datenbankseitig geschütztes Protokoll |
| TOTP und Fernet-Verschlüsselung | neu gebaut, Belegfluss gelesen | `belegfluss/web/portal/totp.py` und `krypto.py` nur als Orientierung für den Replay-Schutz gelesen; eigene Implementierung mit RFC-6238-Testvektoren und MultiFernet-Rotation |
| Lexware-Connector | neu gebaut, Belegfluss gelesen | `belegfluss/lexware.py` zeigte Datumsformat und `shippingConditions` (service/serviceperiod); eigener Connector mit Protokoll, Token-Bucket, Fehlerklassen, Mahnungen, Webhooks und Decimal statt float |
| Layout und CSS | neu gebaut | Eigene mobile Oberfläche; Landingpages und Styles aus Belegfluss werden nicht übernommen |

## Berichte

### Bericht M0 Gerüst (5. November 2026)

**Fertig:** M0-01 Django-Projekt, M0-02 Docker und Makefile, M0-03 CI, M0-04 Job-Queue, M0-05 Protokoll, M0-06 Basis-Layout.

**Tests:** 60 Tests, lokal grün gegen Postgres 16; CI (GitHub Actions) grün für Lint, Typen, Migrations-Check, `check --deploy`, Tests und Docker-Build. Gesamtabdeckung 92 % (Zeilen und Zweige). Die Job-Queue ist mit echtem Postgres getestet, inklusive `SKIP LOCKED` mit zwei parallelen Verbindungen, Backoff, Zeitlimit, Freigabe hängender Jobs, Zeitplan und SIGTERM. Der Trigger des Protokolls ist per direktem SQL getestet.

**Nur lokal statt in Produktion geprüft:** Das Docker-Image wurde lokal und in CI gebaut und startet ohne Root; ein Lauf auf einem Hetzner-Server steht aus (M4-05).

**Belegfluss:** nichts übernommen (siehe Tabelle oben).

**Neue offene Fragen:** keine.

