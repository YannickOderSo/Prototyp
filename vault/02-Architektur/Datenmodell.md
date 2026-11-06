# Datenmodell

Alle fachlichen Tabellen haben `firma_id` (Mandant) und werden ausschließlich über einen Manager abgefragt, der nach `firma` filtert. Geldbeträge als `Decimal(12,2)`, Zinssätze als `Decimal(6,4)`. Zeiten in UTC, Anzeige Europe/Berlin.

## Konto

- **Firma**: name, strasse, plz, ort, email_absender, reply_to, mahn_signatur, zeitzone, aktiv, erstellt (M4-03 ergänzt: mahnplan_bestaetigt_am, einrichtung_fertig_am für den Einrichtungs-Assistenten)
- **Nutzer** (Django User, E-Mail als Login)
- **Mitgliedschaft**: nutzer, firma, rolle (`inhaber` | `freigeber` | `mitarbeiter`). Ein Nutzer kann mehreren Firmen angehören.
- **ZweiFaktor**: nutzer, geheimnis_verschluesselt, letzter_schritt, wiederherstellungscodes_hash[], eingerichtet_am (M1-02: eigene RFC-6238-Implementierung, SHA-1, 6 Stellen, ±1 Schritt Toleranz, jeder Schritt nur einmal gültig; 10 Wiederherstellungscodes als SHA-256; `login()` erst nach dem zweiten Faktor)
- **Einladung**: code_hash, verwendet_am, erstellt_von (umgesetzt mit gueltig_bis, notiz, verwendet_von; Codes erzeugt das Team mit `manage.py einladung_erstellen`, gespeichert nur als SHA-256)
- **TeamEinladung** (ergänzt in M1-01): firma, email, rolle, token_hash, erstellt_von, gueltig_bis (7 Tage), angenommen_am. So lädt der Inhaber Freigeber und Mitarbeiter ein.
- **Zustimmung** (ergänzt in M1-01, F5): nutzer, dokument, version, zeit

## Anbindung

- **Verbindung**: firma, typ (`lexware` | `sevdesk`), schluessel_verschluesselt, status, letzter_abgleich, webhook_ids[], fehler (umgesetzt in M1-06, ergänzt um firmenname_extern, organisation_id, steuerart, kleinunternehmer aus `/v1/profile`, erstimport_fertig, webhook_token für die Callback-URL, getrennt_am; eine Verbindung je Firma und Typ; ein Schlüssel eines anderen Lexware-Kontos wird abgelehnt, solange die alte Verbindung besteht)
- **WebhookEreignis**: verbindung, event_typ, resource_id, empfangen_am, verarbeitet_am, rohdaten (JSON) — für Idempotenz eindeutig auf (verbindung, event_id oder resource_id+zeitstempel)

## Spiegel (aus dem Bestandstool, schreibgeschützt in der App)

- **Kontakt**: extern_id, name, email, kundentyp (`privat` | `unternehmer` | `unbekannt`, **in der App gepflegt**, nicht aus Lexware), mahnpause_bis, notiz
- **Artikel**: extern_id, bezeichnung, einheit, netto, steuersatz, typ
- **Beleg**: extern_id, art (`rechnung` | `angebot` | `abschlag`), nummer, belegdatum, faellig_am, kontakt, brutto, offen, status (`entwurf` | `offen` | `ueberfaellig` | `bezahlt` | `storniert`), bezahlt_am, verzugshinweis_enthalten (bool, Firmeneinstellung oder manuell), mahnpause_bis, aktualisiert_extern

## Mahnen

- **Mahnplan**: firma, tage_erinnerung (7), tage_mahnung1 (21), tage_mahnung2 (35), pauschale_aktiv (true), zinsen_aktiv (true), wochentag_freigabe (Mo), uhrzeit (07:00), vorlagen je Stufe
  Umgesetzt (M2-01) mit zusätzlich: erinnerung_aktiv, abstand_tage (10, Untergrenze 7), frist_mahnung1_tage (10), frist_mahnung2_tage (7), verzugshinweis_auf_rechnungen (Firmeneinstellung für § 286 Abs. 3 bei Privatkunden), bcc_an_firma, automatik_aktiv, betreff_/text_ je Stufe (leer = Standardtext aus `dunning/texte.py`). Abstände zwischen Stufen mindestens 7 Tage (Validierung). Änderungen werden protokolliert.
- **Basiszins**: gueltig_ab, satz — gepflegte Tabelle, Startwerte siehe `Mahnlogik-und-Recht.md` (Data-Migration `dunning/0002`)
- **Mahnvorschlag**: beleg, stufe (0 Erinnerung, 1, 2), erstellt_am, faellig_seit_tagen, offen_betrag, zinsen, pauschale, gesamt, status (`vorgeschlagen` | `freigegeben` | `versendet` | `verworfen` | `fehler`), freigegeben_von, freigegeben_am, verworfen_grund, lexware_dunning_id, eindeutig auf (beleg, stufe)
- **Versand**: vorschlag oder entwurf, empfaenger, betreff, text, anhang_name, message_id, gesendet_am, zustellfehler (umgesetzt mit zustellfehler_am)
- **SmtpZugang** (M2-06, optional je Firma): host, port, benutzer, passwort_verschluesselt, starttls, ssl, absender_adresse, aktiv, geprueft_am. Aktivieren nur nach erfolgreicher Testmail an den Inhaber.

## Erfassen

- **Erfassung**: firma, erstellt_von, kanal (`aufnahme` | `upload` | `mail`), notiz, absender, quelltext, freigegeben_von/am, ziel_art, ziel_url, loeschen_ab (12 Monate) (ergänzt in M3-01), status (`wartet` | `transkribiert` | `extrahiert` | `pruefung` | `freigegeben` | `uebertragen` | `verworfen` | `fehler`), transkript, transkript_bearbeitet, ki_ergebnis (JSON), entwurf (JSON nach Regeln), blocker[], hinweise[], ziel_extern_id, fehler
- **Datei**: erfassung, name, mime, groesse, inhalt (Objektspeicher oder BinaryField mit Limit), loeschen_ab
  Umgesetzt (M3-01): Inhalt als Datei unter `COCKPIT_DATEIABLAGE/<firma_id>/<zufällige ID>` (außerhalb des Webroots, Rechte 0600, im Container das Volume `/data/dateien`), dazu art, sha256 und geloescht_am. Der Typ wird nach den ersten Bytes bestimmt, nicht nach der Endung; Programme, Archive und HTML werden abgelehnt. Grenzen: je Datei 25 MB, je Erfassung 10 Dateien und 50 MB. Nach dem Löschen bleibt der Datensatz (Name, Größe, Hash) als Nachweis.

## Protokoll

- **Protokolleintrag**: firma, nutzer (nullable), zeit, ereignis, objekt_typ, objekt_id, daten (JSON). Nur INSERT. In Postgres per Trigger UPDATE und DELETE verbieten.
  Umgesetzt (M0-05): Trigger `audit_protokoll_schutz` verbietet UPDATE immer und DELETE für Einträge, die jünger als 8 Jahre sind (Löschfrist). Zusätzlich verweigern Modell und QuerySet `save()` auf bestehenden Einträgen, `update()` und `delete()`. Firma und Nutzer sind mit `PROTECT` verknüpft, weil ein `SET NULL` ein UPDATE wäre. TRUNCATE ist nicht per Trigger gesperrt (Testläufe leeren Tabellen damit); der Datenbanknutzer der App bekommt in Produktion kein TRUNCATE-Recht (umgesetzt in M4-05: App-Rolle über `manage.py db_rechte`, Test in `tests/betrieb/test_db_rechte.py`).

## Jobs

- **Job**: typ, payload (JSON), firma, status, versuche, naechster_versuch, gesperrt_bis, fehler, eindeutig_schluessel (optional, für Idempotenz)

## Auswertung im Cockpit (umgesetzt in M1-09, `ledger/auswertung.py`)

- **Offen:** Status offen oder überfällig und offener Betrag > 0; Angebote zählen nie.
- **Überfällig:** Fälligkeit vor heute. Fehlt die Fälligkeit, gilt das Belegdatum.
- **Altersstruktur:** Tage überfällig in den Klassen 1–30, 31–60, 61–90, über 90; noch nicht fällige Posten getrennt.
- **Zahlungsdauer (C3):** Durchschnitt der Tage von Belegdatum bis Zahlung, bezahlte Rechnungen der letzten 12 Monate. Zusätzlich angezeigt: Verzug = Tage von Fälligkeit bis Zahlung.
- **Prognose (C4):** erwarteter Eingang = Fälligkeit + durchschnittlicher Verzug des Kunden (kaufmännisch auf Tage gerundet, nie früher als die Fälligkeit). Vier Wochen ab heute. Liegt der erwartete Termin schon in der Vergangenheit, zählt der Posten als „überfällig, Termin unsicher“ und nicht in die Wochen.
- **C6 (SOLL, umgesetzt):** Tage von Fälligkeit bis Zahlung je Zahlungsmonat, letzte 6 Monate, als Balken.
- **Beleg.mahnstufe:** höchste versendete Stufe; in der App gepflegt (vom Versand gesetzt), für den Filter in C2.

## Import aus Excel (M6, ADR-008)

- **ImportVorgang** (App `datenimport`): firma, art (`kunden` | `artikel` | `posten`), status (`zuordnung` → `vorschau` → `freigegeben` → `fertig` | `fehler` | `verworfen`), dateiname, blatt, spalten, zeilen (gelesene Zellen als Text), zuordnung (Feld → Spaltennummer), standardwerte (z. B. Steuersatz), kundentyp_uebernehmen, vorschau (je Zeile `neu` | `dublette` | `fehler` mit Grund und Daten), ergebnis (je Zeile Lexware-ID bzw. Fehler, für Neuversuche ohne Doppelanlage), erstellt_von, freigegeben_von, freigegeben_am, loeschen_ab (7 Tage), zeilen_geloescht_am. Die Datei selbst wird nicht gespeichert.
- **Kontakt** ergänzt: `adresse` (Rechnungsadresse aus Lexware, für Mahnschreiben der App) und `excel_nummer` (Kundennummer aus dem Excel-Import, nur für die Zuordnung offener Posten; Lexware vergibt eigene Nummern).
- **Beleg** ergänzt: `quelle` (`lexware` | `import`) und `import_vorgang`. Importierte Posten haben `extern_id` = `import-<vorgang>-<zeile>`, werden vom Lexware-Abgleich nie verändert und ihr Zahlstatus wird im Cockpit gepflegt.

## Rechnungskopien und Kontoauszüge (M9, ADR-011 Stufe 3)

App `quellen`. Dateien werden nie gespeichert, nur die gelesenen Felder (K9). Löschfrist für alle vier Tabellen: 12 Monate (`loeschen_ab`).

- **Beleg** ergänzt: `quelle` = `kopie` (Rechnungskopie). `extern_id` = `kopie-<uuid>`. Eigenschaft `lokal` = jede Quelle außer `lexware`; lokale Posten werden vom Lexware-Abgleich nie verändert, ihr Zahlstatus kommt aus Kontoauszügen oder wird von Hand gepflegt.
- **Kontakt** aus einer Kopie oder aus dem Excel-Import ohne Lexware (M9-08): `extern_id` = `lokal-<uuid>`, `kundentyp` = `unbekannt`, bis der Nutzer ihn festlegt (Excel: auf Bestätigung aus der Datei).
- **Kopieadresse**: firma (eindeutig), token (`r` + 16 Hex-Zeichen, Adresse `belege+<token>@…`), aktiv, absender (Liste erlaubter Adressen oder `@domain`), erstellt.
- **Rechnungskopie**: firma, weg (`mail` | `upload`), message_id, dateiname, format (`zugferd` | `xrechnung_cii` | `xrechnung_ubl` | `pdf`), status (`angelegt` | `pruefung` | `doppelt` | `abgelehnt` | `verworfen`), daten (gelesene Felder EN 16931 bzw. KI-Vorschlag, Schlüssel wie im Prüfformular), grund, text (PDF-Text für die KI, nach der Entscheidung geleert), ki_gelesen, beleg, erstellt, erstellt_von, geprueft_von, geprueft_am, loeschen_ab.
- **Kontoauszug**: firma, dateiname, format (`camt053` | `camt052` | `csv`), konto (IBAN gekürzt), von, bis (Stand für K8), gutschriften, neu, doppelt, hochgeladen_von, erstellt, loeschen_ab.
- **Zahlung**: firma, kontoauszug, schluessel (SHA-256; eindeutig je Firma, gegen doppeltes Hochladen), buchungsdatum, betrag, waehrung, zahler, zahler_konto (gekürzt), verwendungszweck (höchstens 500 Zeichen), status (`neu` | `zugeordnet` | `ignoriert`), vorschlag (Beleg aus der Regel), vorschlag_grund, beleg (bestätigt), erledigt_von, erledigt_am, erstellt, loeschen_ab. Nur Gutschriften; Abbuchungen werden beim Lesen verworfen.
