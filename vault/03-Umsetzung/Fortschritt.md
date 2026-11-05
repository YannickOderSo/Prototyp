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
| Mahnautomatik (Recht, Vorschläge, Versand) | neu gebaut | Belegfluss hat kein Mahnwesen mit Verzugsrecht; `rechnen.py` im Portal wurde nicht übernommen, weil es zum eigenen Rechnungsprogramm gehört (ADR-001) |
| CSV-Zeiterfassung (`capture/aufbereitung.py`) | **teilweise übernommen** | Aus `belegfluss/quellen.py` nur die Zuordnung der Spaltennamen gängiger Exporte (Clockify, Toggl, Harvest), mit Vermerk im Code. Begründung nach ADR-007: klar abgegrenzt, Fachwissen über Exportformate, passt ohne Umbau, vorher eigene Tests (`tests/capture/test_aufbereitung.py`). Parser (Dezimalkomma, hh:mm:ss, fehlerhafte Zeilen), Summen und Zeitraum sind neu gebaut |
| Regel-Engine Erfassung (`capture/rules.py`) | neu gebaut, Belegfluss gelesen | `belegfluss/regeln.py` arbeitet mit einer Preisliste aus einer Konfigurationsdatei und übernimmt genannte Preise aus Quellen; beides widerspricht E4/E5 und passt nicht zum Spiegel. Gelesen für die Idee „Mehraufwand gegenüber Angebot“ und den Abgleich mit der Zeiterfassung; Code neu |
| Layout und CSS | neu gebaut | Eigene mobile Oberfläche; Landingpages und Styles aus Belegfluss werden nicht übernommen |

## Berichte

### Bericht M0 Gerüst (5. November 2026)

**Fertig:** M0-01 Django-Projekt, M0-02 Docker und Makefile, M0-03 CI, M0-04 Job-Queue, M0-05 Protokoll, M0-06 Basis-Layout.

**Tests:** 60 Tests, lokal grün gegen Postgres 16; CI (GitHub Actions) grün für Lint, Typen, Migrations-Check, `check --deploy`, Tests und Docker-Build. Gesamtabdeckung 92 % (Zeilen und Zweige). Die Job-Queue ist mit echtem Postgres getestet, inklusive `SKIP LOCKED` mit zwei parallelen Verbindungen, Backoff, Zeitlimit, Freigabe hängender Jobs, Zeitplan und SIGTERM. Der Trigger des Protokolls ist per direktem SQL getestet.

**Nur lokal statt in Produktion geprüft:** Das Docker-Image wurde lokal und in CI gebaut und startet ohne Root; ein Lauf auf einem Hetzner-Server steht aus (M4-05).

**Belegfluss:** nichts übernommen (siehe Tabelle oben).

**Neue offene Fragen:** keine.


### Bericht M1 Konto, Lexware lesen, Cockpit (5. November 2026)

**Fertig:** M1-01 Konten, Rollen, Einladungscodes, Registrierung · M1-02 TOTP-Zwei-Faktor als Pflicht · M1-03 Rate-Limits · M1-04 Mandantentrennung mit generischem IDOR-Test · M1-05 Connector-Protokoll und LexwareConnector · M1-06 Verbindung mit verschlüsseltem Schlüssel · M1-07 Erstimport und Nachtabgleich · M1-08 Webhooks mit Signaturprüfung · M1-09 Cockpit (C1–C5, dazu C6) · M1-10 Kundentyp pflegen.

**Tests:** 205 Tests, lokal grün gegen Postgres 16, Gesamtabdeckung 94 %. CI grün. Abgedeckt sind unter anderem RFC-6238-Testvektoren und Replay-Schutz, 429 nach 10 Fehlversuchen je IP und je Konto, der IDOR-Test über alle URL-Muster mit Parametern, das Fehlen von `finalize` in allen Lexware-Requests (Laufzeitwächter und Quelltextprüfung), ein Lasttest mit 500 Rechnungen und eingestreuten 429, Kennzahlen mit bekannten Summen, Ladezeit der Postenliste bei 1.000 Posten unter 1 s und die Webhook-Signatur mit dem **offiziellen** Beispiel aus der Lexware-Doku.

**Nur gegen Mocks getestet, Echtlauf nötig:**
- Alle Lexware-Aufrufe laufen gegen **nachgebaute** Antworten im Format der Doku (`tests/fixtures/lexware/`), nicht gegen ein echtes Konto. Die Meilenstein-Abnahme M1 („Summen stimmen mit dem Lexware-Testkonto exakt“, „bezahlte Rechnung verschwindet binnen 5 Minuten“) ist nur gegen diese Nachbildung erfüllt. Für den Echtlauf braucht es ein Lexware-Office-XL-Testkonto.
- Webhook-Empfang: Signaturprüfung mit dem echten Lexware-Schlüssel und dem Doku-Beispiel geprüft; Zustellung echter Ereignisse an eine öffentliche HTTPS-Adresse steht aus.
- Das Rate-Limit-Verhalten von Lexware (2/s, 429) ist simuliert, nicht gemessen.

**Belegfluss:** Nichts übernommen. Gelesen wurden `lexware.py` (Datumsformat, `shippingConditions`), `totp.py` und `krypto.py` (Replay-Schutz, Fernet). Alles ist neu gebaut (Tabelle oben).

**Neue offene Fragen:** Altersstruktur nach Tagen überfällig; Prognose ohne Posten mit Termin in der Vergangenheit; Token-Bucket je Prozess; Mahnung nur mit Textposition (Echtlauf). Alle mit Annahme in `05-Kontext/Offene-Fragen.md`.

### Bericht M2 Mahnautomatik (5. November 2026)

**Fertig:** M2-01 Mahnplan und Basiszins-Tabelle · M2-02 Verzugsbeginn, Zinsen, Pauschale als reine Funktionen · M2-03 täglicher Vorschlagslauf · M2-04 Freigabe-Ansicht mit Vorschau · M2-05 Versand-Job mit Frische-Check und Lexware-Mahnung · M2-06 E-Mail-Versand (Plattform oder eigenes SMTP), Zustellfehler · M2-07 Sammelfreigabe-Mail · M2-08 Pausen.

**Tests:** 363 Tests, Gesamtabdeckung 94 %, `dunning` 95,2 % (Vorgabe 90 %), `dunning/recht.py` 100 %. Jede Zeile der Verzugstabelle und jede Zinsregel hat einen Tabellen-Test (Basiszinswechsel zum 1.1. und 1.7., Schaltjahr, Teilzahlung, fehlender Basiszins, unter 1 €, ROUND_HALF_UP). Die Meilenstein-Abnahme ist als Test `tests/dunning/test_abnahme_m2.py` umgesetzt: 20 präparierte Rechnungen ergeben exakt die erwarteten 11 Vorschläge und 2 Klärungsfälle; nach der Freigabe kommen 9 Mails mit den **von Hand gerechneten** Beträgen in Mailpit an, eine bezahlte Rechnung wird vom Frische-Check verworfen, eine geht in den Postversand.

**Nur gegen Mocks getestet, Echtlauf nötig:**
- Lexware: Mahnungsentwurf (`POST /v1/dunnings`), PDF-Abruf und Zahlstatus laufen gegen nachgebaute Antworten. Offen ist insbesondere, ob Lexware eine Mahnung mit nur einer Textposition annimmt und wie das PDF mit den 0-%-Positionen aussieht.
- E-Mail: geprüft gegen Mailpit (lokal und in CI), nicht gegen einen echten EU-SMTP-Anbieter. Zustellbarkeit (SPF, DKIM, DMARC für die Plattformdomain) und Bounce-Format des Anbieters sind offen.
- Die Rechtslogik ist nach dem Vault umgesetzt und getestet, aber nicht juristisch geprüft (M4-07).

**Belegfluss:** nichts übernommen, alles neu gebaut.

**Neue offene Fragen:** Zinsbeginn am Folgetag, 30-Tage-Frist ab dem späteren Datum aus Fälligkeit und Zugang, Zeile 4 der Verzugstabelle (Versand + 2), Privatkunde mit Hinweis und früher Erinnerung, Teilzahlungen im Verzugszeitraum, Pauschale in der 2. Mahnung, Bounce-Format des SMTP-Anbieters. Alle mit schuldnergünstiger Annahme in `05-Kontext/Offene-Fragen.md`.
