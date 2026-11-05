# Datenmodell

Alle fachlichen Tabellen haben `firma_id` (Mandant) und werden ausschließlich über einen Manager abgefragt, der nach `firma` filtert. Geldbeträge als `Decimal(12,2)`, Zinssätze als `Decimal(6,4)`. Zeiten in UTC, Anzeige Europe/Berlin.

## Konto

- **Firma**: name, strasse, plz, ort, email_absender, reply_to, mahn_signatur, zeitzone, aktiv, erstellt
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
- **Basiszins**: gueltig_ab, satz — gepflegte Tabelle, Startwerte siehe `Mahnlogik-und-Recht.md`
- **Mahnvorschlag**: beleg, stufe (0 Erinnerung, 1, 2), erstellt_am, faellig_seit_tagen, offen_betrag, zinsen, pauschale, gesamt, status (`vorgeschlagen` | `freigegeben` | `versendet` | `verworfen` | `fehler`), freigegeben_von, freigegeben_am, verworfen_grund, lexware_dunning_id, eindeutig auf (beleg, stufe)
- **Versand**: vorschlag oder entwurf, empfaenger, betreff, text, anhang_name, message_id, gesendet_am, zustellfehler

## Erfassen

- **Erfassung**: firma, erstellt_von, kanal (`aufnahme` | `upload` | `mail`), status (`wartet` | `transkribiert` | `extrahiert` | `pruefung` | `freigegeben` | `uebertragen` | `verworfen` | `fehler`), transkript, transkript_bearbeitet, ki_ergebnis (JSON), entwurf (JSON nach Regeln), blocker[], hinweise[], ziel_extern_id, fehler
- **Datei**: erfassung, name, mime, groesse, inhalt (Objektspeicher oder BinaryField mit Limit), loeschen_ab

## Protokoll

- **Protokolleintrag**: firma, nutzer (nullable), zeit, ereignis, objekt_typ, objekt_id, daten (JSON). Nur INSERT. In Postgres per Trigger UPDATE und DELETE verbieten.
  Umgesetzt (M0-05): Trigger `audit_protokoll_schutz` verbietet UPDATE immer und DELETE für Einträge, die jünger als 8 Jahre sind (Löschfrist). Zusätzlich verweigern Modell und QuerySet `save()` auf bestehenden Einträgen, `update()` und `delete()`. Firma und Nutzer sind mit `PROTECT` verknüpft, weil ein `SET NULL` ein UPDATE wäre. TRUNCATE ist nicht per Trigger gesperrt (Testläufe leeren Tabellen damit); der Datenbanknutzer der App bekommt in Produktion kein TRUNCATE-Recht (Betriebshandbuch).

## Jobs

- **Job**: typ, payload (JSON), firma, status, versuche, naechster_versuch, gesperrt_bis, fehler, eindeutig_schluessel (optional, für Idempotenz)
