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
| Betrieb: Produktions-Compose, Sicherung, Ausrollen, Health, Löschfristen | neu gebaut | ADR-007 schließt die Deploy-Skripte aus Belegfluss aus; Caddy-Stack, App-Rolle ohne TRUNCATE, restic-Skripte, Release per Tag, `/healthz` und Löschjob sind eigene Arbeit nach Sicherheit-Datenschutz-Betrieb.md |
| Wochenbericht, Export, Onboarding | neu gebaut | Kein Gegenstück in Belegfluss |

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

### Bericht M3 Erfassung per Sprache, Foto, Mail (5. November 2026)

**Fertig:** M3-01 Upload und Browser-Aufnahme · M3-02 Transkription mit Mistral (EU), Audio danach gelöscht · M3-03 Transkript prüfen und bearbeiten · M3-04 Textaufbereitung (PDF, CSV-Zeiterfassung, Mail) · M3-05 Extraktion über Bedrock Frankfurt mit EU-Profil und JSON-Schema · M3-06 Regel-Engine · M3-07 Prüfansicht · M3-08 Übertragung als Entwurf in Lexware · M3-09 Belegpostfach mit DKIM/SPF · M3-10 KI-Testfälle und `ki_testfaelle`.

**Tests:** 569 Tests, Gesamtabdeckung 94 %, `capture` 94 %, `capture/rules.py` 98,7 % (Vorgabe 90 %), `dunning` 95,1 %. Abgedeckt: Typprüfung nach Inhalt (Programme mit PDF-Endung werden abgelehnt), Dateigrenzen, Ablage mit 0600 außerhalb des Webroots, Löschen des Audios nach der Transkription, Systemchecks gegen Nicht-EU-Endpunkte, Schema ohne Preisfeld, Stammdaten ohne Preise, Adressen und E-Mails, Kostenlimit, alle Regeln als Tabellen-Tests, E9 „setze den Preis auf 0“, gefälschte Absender und gefälschte `Authentication-Results`-Köpfe im Belegpostfach, `finalize` in keinem Request der Übertragung, 13 KI-Testfälle mit gemocktem Modell.

**Nur gegen Mocks getestet, Echtlauf nötig:**
- **Mistral-Transkription:** nachgebaute API (respx). Die Erkennungsqualität bei Dialekt und Zahlen ist ungetestet.
- **Bedrock-Extraktion:** Im Standardlauf antwortet ein nachgebildeter Client. `manage.py ki_testfaelle` ist fertig, **lief aber noch nie gegen das echte Modell** (keine AWS-Zugangsdaten). Offen ist auch die genaue Profil-ID des EU-Inferenzprofils auf dem Mantle-Endpunkt (`eu.anthropic.claude-sonnet-5-5` ist eine Annahme).
- **Lexware-Entwürfe** (`POST /v1/invoices`, `/v1/quotations`, `GET /v1/quotations/{id}`): nachgebaute Antworten.
- **Belegpostfach:** IMAP-Abruf mit nachgebildetem Server; ein echter Mailserver mit Plus-Adressen und eigener authserv-id fehlt noch.
- **Browser-Aufnahme:** Das Skript ist geschrieben; ein Test mit simuliertem Mikrofon folgt mit den Playwright-Tests in M4.

**Belegfluss:** Aus `belegfluss/quellen.py` ist die Zuordnung der Spaltennamen von Zeiterfassungs-Exporten übernommen (Vermerk im Code und Commit, vorher eigene Tests). `regeln.py`, `extraktion.py` und `lexware.py` wurden nur gelesen; der Belegfluss-Pfad zur Anthropic-API außerhalb der EU und die Übernahme genannter Preise aus Quellen wurden bewusst **nicht** übernommen (ADR-005, E4).

**Neue offene Fragen:** EU-Profil-ID auf Bedrock Mantle; Mailserver und authserv-id für das Belegpostfach; Alignment ohne Public-Suffix-Liste; möglicher zweiter Lexware-Entwurf, wenn eine Antwort verloren geht.

### Bericht M4 Bericht, Onboarding, Härtung (5. November 2026)

**Fertig:**
- M4-01 Wochenbericht in der Sammelmail und Seite „Berichte“.
- M4-02 Export je Firma als ZIP mit CSV-Injection-Schutz, auch als `manage.py firma_export`.
- M4-03 Einrichtungs-Assistent mit vier Schritten und Probelauf ohne Speichern und ohne Versand.
- M4-04 Täglicher Löschjob nach allen Fristen, dazu `manage.py firma_loeschen`.
- M4-05 Produktions-Stack:
  - Caddy mit HTTPS,
  - App-Rolle ohne TRUNCATE, ohne DDL und ohne UPDATE auf das Protokoll,
  - restic-Sicherung, Restore-Probe und Wiederherstellung,
  - `/healthz`, Fehlererfassung nur in der EU,
  - Smoke-Test des kompletten Stacks in der CI, Release per Tag.
- M4-06 Betriebshandbuch, dazu `basiszins_setzen`, `schluessel_rotieren` und `DJANGO_SECRET_KEY_FALLBACKS`.
- M4-07 Prüfliste für das Team, dazu Systemcheck `cockpit.W001` gegen Platzhalter-Rechtstexte.
- Außerdem: Playwright-Tests der drei Hauptabläufe auf 390 × 844.

**Tests:**
- 643 Tests, davon 3 Playwright-Tests.
- Abdeckung: gesamt 95 %, `dunning` 95,3 %, `capture/rules.py` 98,7 % (Vorgabe jeweils 90 %).
- Neu abgedeckt:
  - Löschfristen mit Mandantentrennung und Protokoll nach 8 Jahren gegen den echten Trigger.
  - Rechte der App-Rolle gegen echtes Postgres: TRUNCATE, DDL und UPDATE auf das Protokoll werden abgewiesen.
  - Sicherung, Restore-Probe und Wiederherstellung gegen echtes Postgres mit nachgebautem restic.
  - Health-Endpoint, darunter der Worker-Ausfall binnen 5 Minuten.
  - Bereinigung der Fehlerereignisse, EU-Systemcheck für die Fehlererfassung, Rotation der Fernet-Schlüssel, Pflege des Basiszinses.
- Die Playwright-Tests melden sich über die Oberfläche mit TOTP an und prüfen auf jeder Seite, dass es kein horizontales Scrollen gibt.
- `scripts/prod_smoke.sh` startet das Produktions-Compose mit dem gebauten Image. Er lief lokal und in der CI grün. Geprüft werden:
  - Rollen-Init, Migration als Eigentümer, Betrieb als App-Rolle,
  - HTTPS über Caddy, Sicherheitsheader, Formular-POST mit CSRF hinter dem Proxy,
  - kein TRUNCATE für die App-Rolle,
  - Sicherung und Restore-Probe mit **echtem** restic in ein lokales Repository.

**Nur gegen Mocks oder lokal getestet, Echtlauf nötig:**
- Die drei Playwright-Abläufe laufen gegen nachgebautes Lexware, Mistral und Bedrock. Die Jobs führt der Test aus, nicht ein eigener Worker-Prozess.
- Der Produktions-Stack lief nur lokal und in der CI, nicht auf einem Hetzner-Server:
  - Caddy nutzte die interne Zertifizierungsstelle für `localhost`, nicht Let's Encrypt.
  - restic sicherte in ein lokales Repository, nicht auf die Storage Box per SFTP.
  - Der Deploy-Job per SSH in `release.yml` lief noch nie.
- Fehlererfassung: Die Bereinigung ist getestet, ein echtes Senden an GlitchTip oder Sentry nicht.
- Der Uptime-Check von außen ist nicht eingerichtet.

**Belegfluss:** In M4 nichts übernommen. Deploy-Skripte und Landingpages aus Belegfluss sind nach ADR-007 ausgeschlossen. Betrieb, Löschfristen, Export, Wochenbericht und Onboarding sind neu gebaut.

**Neue offene Fragen:**
- Werden Mahnvorschläge und Versände mit den Spiegeldaten gelöscht? Annahme: ja.
- Fristen für technische Reste (Jobs, Webhook-Ereignisse, Postfach-Eingänge).
- Nutzer nach der Löschung einer Firma: deaktiviert, bleiben als Bezug des Protokolls.
- Teilzahlungen im Wochenbericht.
- Eine Sammelaktion „Firmenkunden als Unternehmer markieren“ wurde verworfen. Mahnlogik-und-Recht.md verbietet, den Lexware-Hinweis Firma/Person zu übernehmen.

## Abschluss MVP M0–M4 (5. November 2026)

Alle Tickets M0-01 bis M4-07 sind abgehakt. Die CI prüft:
- Ruff, mypy und Migrations-Check,
- `check --deploy`,
- pytest mit Postgres und Mailpit, Abdeckungsgrenzen,
- Playwright,
- Docker-Build und Smoke-Test des Produktions-Stacks.

Das Betriebshandbuch liegt in [[Betriebshandbuch]], die Prüfliste für das Team in [[Pruefliste-Team]].

**Lokale Demo:**
- Start mit `manage.py demo_daten`, Anleitung in der README.
- Angelegt werden eine Demo-Firma, Rechnungen in allen Altersstufen, die heutigen Mahnvorschläge und eine Erfassung in der Prüfansicht.
- Der Demo-Connector (`connectors/demo.py`) wird nur mit `DJANGO_DEBUG=true` und nur für die Demo-Verbindung verwendet. Er arbeitet ausschließlich auf der eigenen Datenbank und sendet keine Anfrage nach außen; ein Test prüft das. Freigegebene Mahnungen gehen so lokal als Mail mit Demo-PDF an Mailpit.
- Neue Sprachmemos oder Uploads brauchen in der Demo echte Mistral- und AWS-Zugänge, sonst enden sie mit „Fehler“.

**Definition of Done (00-Start-hier.md), Punkt für Punkt:**

| Punkt | Stand |
| --- | --- |
| Pilot mit Lexware Office XL kann sich anmelden | erfüllt: Einladung, Registrierung und Pflicht-2FA mit Tests; die Anmeldung mit TOTP-Code läuft auch in allen drei Playwright-Tests |
| hinterlegt seinen Lexware-Schlüssel | erfüllt gegen nachgebaute API; **offen für Echtlauf** |
| sieht binnen 2 Minuten seine offenen Posten nach Alter | erfüllt gegen nachgebaute API (Erstimport, Altersstruktur); Dauer mit echtem Konto **offen für Echtlauf** |
| gibt montags die Vorschläge frei | erfüllt: Vorschlagslauf 5 Uhr, Sammelmail montags 7 Uhr, Freigabe nur angemeldet mit 2FA durch Inhaber/Freigeber |
| Mails gehen korrekt mit PDF an die Kunden | erfüllt gegen nachgebaute Lexware-PDFs, locmem und Mailpit; echter SMTP-Anbieter **offen für Echtlauf** |
| Sprachmemo aufnehmen → Rechnungsentwurf in Lexware | erfüllt mit Fake-Mikrofon, nachgebautem Mistral, Bedrock und Lexware; **offen für Echtlauf** |
| alles ist protokolliert | erfüllt: Protokoll mit Datenbank-Trigger, jeder Schritt mit Außenwirkung, Export |
| läuft auf einem Server in Deutschland | Stack fertig und lokal und in der CI geprüft; Server **offen für Echtlauf** |
| mit automatischen Tests abgedeckt | erfüllt: 643 Tests, Abdeckung 95 % |

**Offen für Echtlauf** (Details und Reihenfolge im Betriebshandbuch, Abschnitt 10):
1. Hetzner-Server und Storage Box, Domain und Let's Encrypt. Erste echte Sicherung und Restore-Probe auf dem Server. Deploy-Job per Tag mit hinterlegten Zugangsdaten.
2. Lexware Office XL eines Piloten. Prüfen:
   - Erstimport unter 2 Minuten mit echten Datenmengen,
   - Webhook-Zustellung und Signatur,
   - Nachtabgleich,
   - Annahme der Mahnung mit nur einer Textposition,
   - Entwürfe bleiben Entwurf (`finalize` wird nie gesendet; die Tests prüfen das für alle Anfragen).
3. Amazon Bedrock in `eu-central-1`:
   - Modellzugang und genaue ID des EU-Inferenzprofils klären,
   - `manage.py ki_testfaelle` mit echten Schlüsseln laufen lassen.
4. Mistral-Transkription mit echten Sprachmemos (Dialekt, Zahlen).
5. EU-SMTP-Anbieter auswählen (ADR), SPF, DKIM und DMARC einrichten. Adapter für dessen Bounce-Format schreiben.
6. Mailanbieter für das Belegpostfach mit Plus-Adressen und authserv-id.
7. Fehlererfassung (GlitchTip oder Sentry EU) und Uptime-Check von außen.
8. Die Prüfliste für das Team abarbeiten:
   - Rechtstexte statt Platzhaltern,
   - AVV und Verträge mit Unterauftragsverarbeitern,
   - Prüfung von Mahntexten und Zinslogik durch Anwalt und Steuerberater,
   - Versicherung.

## Bericht M6 Import aus Excel (5. November 2026)

Wunsch von Yannick: Betriebe, die bisher nur mit Excel gearbeitet haben, sollen alles übernehmen können. Entscheidung in [[ADR-008-Import-aus-Excel]], Anforderungen H1–H9.

**Fertig:**
- M6-01 Spezifikation, ADR-008, Datenmodell (`ImportVorgang`, `Beleg.quelle`, `Kontakt.adresse`, `Kontakt.excel_nummer`).
- M6-02 Einlesen von `.xlsx` und CSV: Tabellenblatt wählbar, Semikolon oder Komma, UTF-8 oder Windows-1252, deutsche Zahlen und Daten, Excel-Seriendaten. Schutz gegen übergroße und gepackte Dateien (10 MB, 50 MB entpackt, 5.000 Zeilen, 50 Spalten); `.xls` wird mit Hinweis abgelehnt.
- M6-03 Spaltenzuordnung mit Vorschlägen aus den Überschriften; Vorlagen als Excel und CSV.
- M6-04 Kunden nach Lexware (`POST /v1/contacts`): Firma oder Person, Ansprechpartner, E-Mail, Rechnungsadresse; Kundennummer aus Excel als Notiz (Lexware vergibt die Nummer selbst). Kundentyp nur nach ausdrücklicher Bestätigung, mit Protokoll.
- M6-05 Artikel nach Lexware (`POST /v1/articles`): Preise als Dezimalzahl ohne float, Steuersatz nur 0, 7 oder 19 %, Brutto wird mit kaufmännischer Rundung in netto umgerechnet. Preise kommen nur aus der Datei oder einem Standardwert des Nutzers, nie aus der KI.
- M6-06 Alte offene Rechnungen nur im Cockpit (Quelle „import“), vom Lexware-Abgleich ausgenommen; Zahlstatus von Hand (bezahlt am oder neuer offener Betrag), protokolliert.
- M6-07 Mahnen importierter Posten nach denselben Regeln: Frische-Check gegen den Cockpit-Stand, Erinnerung per Mail ohne Anhang, Mahnung und Brief als Mahnschreiben-PDF der App. Lexware wird für diese Posten nie aufgerufen; die Freigabe weist auf den von Hand gepflegten Zahlstatus hin.
- M6-08 Oberfläche unter Einstellungen → Import aus Excel und als Hinweis im Einrichtungs-Assistenten: hochladen, zuordnen, Vorschau (neu, Dublette, Fehler mit Grund, bezahlt), Freigabe nur durch Inhaber oder Freigeber, Ergebnis je Zeile, „Import fortsetzen“ nach einem Abbruch. Zahlungsformular auf der Belegseite importierter Rechnungen, Kennzeichen „aus Excel“ in der Postenliste. IDOR-Fälle ergänzt, Löschfrist der Importzeilen nach 7 Tagen, `firma_loeschen` löscht Importe.

**Tests:** 739 Tests (736 ohne und 3 mit Playwright). Neu unter anderem:
- Vorschau aller drei Arten mit Dubletten gegen Spiegel und Datei.
- Anlage per Job gegen nachgebaute Lexware-API mit genauem Request-Format.
- Neuversuch ohne Doppelanlage, Fortsetzen nach abgelehntem Schlüssel, dauerhafter Fehler je Zeile.
- Mahnen importierter Posten ohne einen einzigen Lexware-Aufruf.
- PDF-Inhalt des Mahnschreibens, Löschfrist, Rollen und Mandantentrennung.
- Die Oberfläche wurde zusätzlich in der lokalen Demo auf 390 px Breite durchgeklickt.

**Nur gegen Mocks getestet, Echtlauf nötig:**
- Anlage von Kontakten und Artikeln in einem echten Lexware-Konto. Das Request-Format folgt der Doku.
- Ungeprüft ist, ob Lexware Ansprechpartner, Notiz und Adresse genau so übernimmt.
- Excel-Dateien aus echten Betrieben (Spaltennamen, Formate) für bessere Vorschläge sammeln.

**Belegfluss:** nichts übernommen; der Import ist neu gebaut.

## Klick-Demo auf GitHub Pages (5. November 2026)

Wunsch: die Webapp zunächst unter GitHub Pages zeigen. GitHub Pages liefert nur statische Dateien aus und steht nicht unter EU-Kontrolle; die echte App (Django, Postgres, Worker) kann dort nicht laufen und darf es nach ADR-005 auch nicht. Deshalb gibt es dort eine **statische Klick-Demo**:
- `manage.py statische_demo <ziel>` rendert die Seiten der Demo-Firma im Prozess (nur GET) als HTML mit relativen Links. Nur mit `DJANGO_DEBUG=true` und nur für die Demo-Firma aus `demo_daten`.
- Entfernt werden CSRF-Token und htmx. Anmeldung, Webhooks, Lexware-Schlüssel und SMTP-Seiten werden nicht übernommen.
- Formulare und Knöpfe zeigen nur „Nur Demo“. Ein Banner auf jeder Seite kennzeichnet die Demo.
- Workflow `.github/workflows/pages.yml`: Postgres-Service, Demo-Daten, statische Seiten, Veröffentlichung mit `actions/deploy-pages`. Keine Secrets.
- Einmalig nötig im Repository: Pages-Quelle „GitHub Actions“ und `build/mvp` für die Umgebung `github-pages` erlauben (README).
- Die Demo-Daten enthalten jetzt auch einen Excel-Import alter Rechnungen in der Vorschau.

## Neues Design der Oberfläche (5. November 2026)

Wunsch: die Oberfläche professioneller und schöner. Vorbilder:
- Mercury: ruhige, vertrauensbildende Finanz-Optik.
- Stripe: klare Tabellen mit rechtsbündigen Beträgen.
- Material: untere Navigation auf dem Handy mit 3 bis 5 Zielen.

**Umgesetzt:**
- Neues Design-System mit Farb-, Abstands- und Schattenvariablen.
- Schrift Inter, selbst gehostet. Icons von Lucide, inline als SVG.
- Status als Plaketten mit Punkt, Zahlen in fester Breite.
- **Desktop:** feste Seitenleiste mit Firmenname und Zählern, z. B. offene Freigaben und Entwürfe zur Prüfung.
- **Handy:** schlanke Kopfzeile und eine untere Leiste mit vier Hauptzielen plus „Mehr“.
- Cockpit zweispaltig ab Tablet.
- Feste Aktionsleiste „Markierte freigeben“ unter langen Freigabelisten.
- Anmeldeseiten als schmale, zentrierte Karte.
- Weiterhin keine Inline-Styles und keine fremden Server. Alle Tests und die drei Playwright-Abläufe sind grün, auch auf 390 px ohne horizontales Scrollen.

## Marke Belegfluss (5. November 2026)

Der Produktname ist **Belegfluss**. Logo-Entwurf: Ein Kassenbon steht für den „Beleg“, zwei fließende Wellen statt Textzeilen für den „Fluss“. Vier Varianten wurden verglichen, gewählt wurde die, die auch bei 16 px als Favicon lesbar bleibt.

**Eingebaut:**
- Seitenleiste, Kopf auf dem Handy, Anmeldeseiten, Seitentitel, Favicon und Apple-Touch-Icon.
- Einladungs- und Passwort-Mails, Testmail, Sammelmail-Link und Name in der Authenticator-App.
- Alle Texte, in denen „das Cockpit“ das Produkt meinte. „Cockpit“ heißt weiter die Übersichtsseite.

**Nicht geändert:** Python-Paket `cockpit` und Django-Projekt. Der Aufwand stünde in keinem Verhältnis, und Migrationen sowie Deploy hängen daran.

## Bericht M7 Rückmeldung Lukas (5. November 2026)

Lukas hat 10 Punkte geschickt. Yannick hat entschieden:
- die schnellen Punkte bauen,
- „Erfassen“ heißt „Angebote & Rechnungen“,
- die Angebots-Erinnerung geht nach Freigabe an den Endkunden.

Die großen Punkte stehen als Konzept in [[Konzept-Erweiterungen]]: Abo-Verwaltung, Team-Chat, KI-Hilfe-Chat, KI-Telefonassistent.

**Fertig:**
- M7-01 Spezifikation I1–I7, [[ADR-009-Angebots-Erinnerung]], Konzept mit Aufwand, Rechtsfragen und Empfehlung.
- M7-02 Angebote im Spiegel: Ablaufdatum aus `GET /v1/quotations/{id}` (nur bei Bedarf), Status „angenommen“ und „abgelehnt“, Abgleich der letzten 12 Monate.
- M7-03 „Angebote & Rechnungen“ mit Einstieg „Angebot oder Rechnung erstellen“, Entwürfen und offenen Angeboten. Das Cockpit hat Reiter: Überblick, Rechnungen, Angebote, Mahnungen.
- M7-04 Statistik statt Berichte: 7 Tage, dieser Monat, letzter Monat; neu mit Angeboten (verschickt, angenommen, abgelehnt, abgelaufen, Quote), auch in der Montagsmail.
- M7-05 Angebots-Erinnerung an den Endkunden:
  - Vorschlag 7 Tage vor Ablauf.
  - Freigabe mit zweitem Faktor.
  - Frische-Check in Lexware.
  - Angebots-PDF im Anhang.
  - Protokoll, Export und Zähler.
- M7-06 Profil mit spielerischem Avatar (20 Symbole, 6 Farben), Profil-Link in der Seitenleiste und im Handy-Kopf, Avatare in der Team-Liste. „Abo und Zahlung“ ist als „kommt bald“ angekündigt.
- M7-07 Aufklappbarer Hinweis zur E-Rechnung im Rechnungsentwurf an Unternehmen und auf der Lexware-Seite. Lexware erzeugt die E-Rechnung (ADR-001).
- Punkt 7 (PDF im Anhang) war schon umgesetzt: Erinnerungen tragen die Rechnung, Mahnungen das Lexware-PDF. Neu ist das Angebots-PDF bei Angebots-Erinnerungen.

**Nur gegen Mocks getestet, Echtlauf nötig:**
- Ablaufdatum und Status echter Lexware-Angebote.
- Das Angebots-PDF (`/v1/quotations/{id}/file`).
- Prüfen, ob die Belegliste `voucherDateFrom` für Angebote wie dokumentiert filtert.

## Bericht M8 KI-Telefonassistent, Prototyp (5. November 2026)

Wunsch von Lukas (Punkt 10). Yannick hat entschieden: Live-Gespräch mit KI, im Pilot für alle Betriebe einschaltbar. Die Entscheidung steht in [[ADR-010-KI-Telefonassistent]].

**Gebaut (App `telefon`):**
- Feste Ansage mit Pflichthinweis: digitaler Assistent, Umwandlung in Text, Auflegen möglich, Notruf 112. Die Begrüßung ist je Betrieb anpassbar.
- Gesprächsführung mit Claude über Bedrock EU und strukturierter Antwort. Sie erfragt Name, Anliegen, Rückrufnummer, Dringlichkeit und die beste Zeit.
- Der Code prüft jede Antwort und ersetzt Beträge und Terminzusagen. Höchstens 8 Runden.
- Ausfallbetrieb mit festen Fragen, wenn die KI ausfällt, das Limit erreicht ist oder Zugangsdaten fehlen. Auch wer aufgelegt hat, erzeugt eine Notiz.
- Rückruf-Notizen mit Dringlichkeit, „erledigt“ samt interner Notiz und Zähler in der Navigation. Die Mail ans Team nennt nur Name, Dringlichkeit und Link.
- Testanruf im Browser per Text oder Mikrofon. Die Antwort liest eine lokale Stimme des Browsers vor.
- Telefonie:
  - Anmeldung durch Asterisk per HTTPS mit Geheimnis; die Firma wird über die angerufene Nummer zugeordnet.
  - AudioSocket-Dienst `telefon_dienst` mit Sprechpausen-Erkennung, Voxtral je Beitrag und Piper-Sprachausgabe. Audio wird nie gespeichert.
- Beispielkonfiguration für Asterisk, Betriebshandbuch Abschnitt 11, Löschfristen (90 Tage bzw. 12 Monate), IDOR-Fälle, Demo-Daten.

**Tests:** 25 neue Tests, darunter ein simulierter Anruf über AudioSocket von der Ansage über zwei Runden bis zur Notiz, Auflegen nach der Ansage, eine unbekannte UUID und Piper mit Ersatzprogramm. Der Testanruf wurde im Browser durchgeklickt. Lokal lief er im Ausfallbetrieb, weil hier kein freigeschalteter AWS-Zugang besteht.

**Nicht getestet, vor echten Anrufen nötig:**
- Kein echter Anruf: Es gibt noch keinen SIP-Trunk und keine Rufnummer, Asterisk ist nicht installiert.
- Keine echte Piper-Stimme und kein Bedrock-Aufruf mit echtem Modell; die Antwortzeit ist ungemessen.
- Die Sprechpausen-Erkennung ist nur mit synthetischem Audio getestet. Schwellwerte mit echten Telefonaten einstellen.
- Rechtliche Prüfung von Ansage und AVV. Die Lizenz der Stimme prüfen.
