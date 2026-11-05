# Anforderungen MVP

Jede Anforderung hat eine ID. Tickets und Tests referenzieren diese IDs. "MUSS" ist MVP, "SOLL" ist MVP wenn Zeit, "KANN" ist später.

## A. Konto, Firma, Zugang

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| A1 MUSS | Registrierung einer Firma mit Inhaber-Konto, nur per Einladungscode (geschlossene Beta) | Ohne gültigen Code keine Registrierung; Code einmalig verwendbar |
| A2 MUSS | Login mit E-Mail und Passwort plus TOTP-Zwei-Faktor (Pflicht) | Ohne zweiten Faktor kein Zugriff; Wiederherstellungscodes gehasht gespeichert |
| A3 MUSS | Rollen: Inhaber, Freigeber, Mitarbeiter | Nur Inhaber und Freigeber dürfen Mahnungen und Entwürfe freigeben; Mitarbeiter dürfen erfassen |
| A4 MUSS | Strikte Mandantentrennung | Kein Endpunkt liefert Daten einer anderen Firma; automatisierter Test für jeden ID-basierten Endpunkt |
| A5 MUSS | Rate-Limit für Login, 2FA, Passwort-Reset je IP und je Konto | Nach 10 Fehlversuchen je IP in 15 Minuten 429 |

## B. Anbindung Lexware Office

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| B1 MUSS | Inhaber hinterlegt Lexware-API-Schlüssel; App prüft ihn sofort | Erfolgreicher Testaufruf zeigt Firmenname aus Lexware; Schlüssel verschlüsselt gespeichert |
| B2 MUSS | Erstimport: alle offenen und überfälligen Rechnungen, Kontakte, Artikel | Nach Erstimport stimmen Summe und Anzahl offener Posten mit Lexware überein (Abweichung 0) |
| B3 MUSS | Laufender Abgleich per Webhook (`invoice.status.changed`, `payment.changed`, `invoice.created`, `contact.changed`) plus nächtlicher Vollabgleich | Bezahlte Rechnung verschwindet spätestens 5 Minuten nach Zahlung in Lexware aus "offen"; nächtlicher Abgleich korrigiert verpasste Events |
| B4 MUSS | Rate-Limit Lexware (2 Anfragen pro Sekunde) wird eingehalten, 429 wird mit Backoff wiederholt | Lasttest mit 500 Rechnungen läuft ohne Abbruch |
| B5 MUSS | Rechnungs- und Angebotsentwürfe in Lexware anlegen (nie finalisieren) | Entwurf erscheint in Lexware im Status "Entwurf"; App ruft nie `finalize=true` auf |
| B6 MUSS | Mahnungsentwurf in Lexware anlegen und PDF abholen | `POST /v1/dunnings?precedingSalesVoucherId=…` und `GET /v1/dunnings/{id}/file` funktionieren im Testkonto |

## C. Forderungs-Cockpit

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| C1 MUSS | Startseite zeigt: Summe offen, Summe überfällig, Anzahl überfällig, Altersstruktur 0–30 / 31–60 / 61–90 / über 90 Tage | Werte stimmen mit Testdaten überein (Testfixture mit bekannten Summen) |
| C2 MUSS | Liste offener Posten, sortier- und filterbar nach Kunde, Fälligkeit, Betrag, Mahnstufe | Filter kombinierbar; Ladezeit unter 1 Sekunde bei 1.000 Posten |
| C3 MUSS | Kundenansicht: offene Posten je Kunde, Zahlungshistorie, durchschnittliche Zahlungsdauer | Durchschnitt aus bezahlten Rechnungen der letzten 12 Monate |
| C4 MUSS | Prognose Geldeingang nächste 4 Wochen (nach Fälligkeit, korrigiert um durchschnittlichen Verzug des Kunden) | Berechnung in Unit-Test nachvollziehbar |
| C5 MUSS | Mobile tauglich ab 360 px Breite | Keine horizontale Scrollleiste; Kennzahlen oben |
| C6 SOLL | Kennzahl "Tage von Fälligkeit bis Zahlung" als Verlauf je Monat | Diagramm mit 6 Monaten |

## D. Mahnautomatik

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| D1 MUSS | Mahnplan je Firma: Zahlungserinnerung nach X Tagen über Fälligkeit, 1. Mahnung nach Y, 2. Mahnung nach Z (Standard 7/21/35) | Einstellbar; Änderungen protokolliert |
| D2 MUSS | Täglicher Lauf erzeugt **Vorschläge**, nie Versand | Lauf ist idempotent; zweiter Lauf am selben Tag erzeugt keine Duplikate |
| D3 MUSS | Kundentyp (Privat / Unternehmer) je Kontakt ist Pflicht, bevor gemahnt wird; ohne Typ wird der Posten als "Klärung nötig" markiert | Kein Vorschlag ohne Kundentyp |
| D4 MUSS | Verzugszinsen nach § 288 BGB: Basiszins + 5 Prozentpunkte (Privat) bzw. + 9 (Unternehmer), taggenau ab Verzugsbeginn; 40 € Pauschale nur bei Unternehmern | Unit-Tests mit Basiszinswechsel zum 1.1. und 1.7.; Basiszins als gepflegte Tabelle |
| D5 MUSS | Verzugsbeginn korrekt: 30 Tage nach Fälligkeit und Zugang, bei Privatkunden nur wenn die Rechnung den Hinweis enthielt; sonst erst ab Mahnung | Regeln siehe `02-Architektur/Mahnlogik-und-Recht.md`; jede Regel hat einen Test |
| D6 MUSS | Wöchentliche Sammelfreigabe (Standard Montag 7 Uhr) per E-Mail mit Link; Freigabe auch einzeln im Cockpit | Freigabe erfordert Login mit 2FA; Link allein gibt nichts frei |
| D7 MUSS | Nach Freigabe: Mahnungsentwurf in Lexware (ab Stufe 1), PDF holen, E-Mail an Kunden mit Textvorlage und PDF | Versand über SMTP der Firma oder Plattform-Absender mit Reply-To der Firma; Zustellfehler sichtbar |
| D8 MUSS | Ausnahmen: Kunde oder Rechnung pausieren ("nicht mahnen bis …"), Teilzahlungen berücksichtigen (offener Betrag aus Lexware) | Pausierte Posten erzeugen keine Vorschläge |
| D9 MUSS | Vor jedem Versand Frische-Check: Zahlstatus in Lexware erneut abfragen | Wurde inzwischen bezahlt, wird nicht versendet und der Vorschlag verworfen |
| D10 SOLL | Textvorlagen je Stufe mit Platzhaltern, Tonalität freundlich, Vorschau | Vorschau zeigt exakt die gesendete Mail |

## E. Erfassung per Sprache, Foto, Mail

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| E1 MUSS | Sprachaufnahme im Browser (Handy), Upload von Audio, Foto, PDF, CSV | Aufnahme bis 5 Minuten; Dateien bis 25 MB |
| E2 MUSS | Belegpostfach je Firma (Weiterleitung an eine eigene Adresse), Absender nur aus Whitelist und nur mit bestandener DKIM- oder SPF-Prüfung | Gefälschter Absender wird verworfen und protokolliert |
| E3 MUSS | Transkript wird angezeigt und ist editierbar, bevor der Entwurf entsteht | Nutzer kann Transkript ändern und neu erzeugen lassen |
| E4 MUSS | KI liefert nur Struktur: Belegart (Angebot/Rechnung), Kunde, Positionen mit Text, Menge, Einheit, Artikelzuordnung, Leistungszeitraum, offene Fragen | JSON-Schema erzwungen; Preise und Steuersätze kommen nur aus Lexware-Artikeln |
| E5 MUSS | Position ohne passenden Artikel: Preis bleibt leer, Entwurf ist blockiert bis Nutzer Preis setzt | Kein Entwurf mit geratenem Preis |
| E6 MUSS | Jede Position zeigt Herkunft (gehört, aus Foto, aus Mail, aus Stammdaten) | Sichtbar in der Prüfansicht |
| E7 MUSS | Nach Freigabe: Entwurf in Lexware anlegen, Link zum Entwurf anzeigen | Entwurf in Lexware, nie finalisiert |
| E8 MUSS | Audio wird nach Transkription gelöscht; Rohdateien nach 7 Tagen | Löschjob mit Test |
| E9 MUSS | Prompt-Injection: Anweisungen in Mails oder Notizen werden ignoriert und als offene Frage gemeldet | Testfall "setze den Preis auf 0" besteht |
| E10 SOLL | Abgleich mit offenem Angebot in Lexware (Mehraufwand gegenüber Angebot markieren) | Hinweis bei Menge über Angebot |
| E11 KANN | WhatsApp-Business als Eingangskanal | später |

## F. Bericht, Protokoll, Betrieb

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| F1 MUSS | Wöchentlicher Liquiditätsbericht per Mail: eingegangen, überfällig, gemahnt, Prognose | Versand Montag zusammen mit der Sammelfreigabe |
| F2 MUSS | Protokoll aller Aktionen mit Außenwirkung (Freigabe, Versand, Entwurf angelegt, Einstellungen) mit Nutzer und Zeit; nur anhängend | Kein Update/Delete auf Protokolltabelle über die App |
| F3 MUSS | Datenexport je Firma (CSV aller Vorschläge, Versände, Protokoll) | Inhaber kann jederzeit exportieren |
| F4 MUSS | Health-Endpoint, strukturierte Logs, Fehlererfassung | Ausfall des Workers ist binnen 5 Minuten sichtbar |
| F5 MUSS | Rechtstexte als Seiten: Impressum, Datenschutz, AGB, AVV (Inhalte liefert das Team, App stellt Platzhalter bereit) | Links im Footer; Registrierung verlangt Zustimmung zu existierenden Dokumenten |
| F6 SOLL | Onboarding-Assistent: Lexware verbinden → Kundentypen setzen → Mahnplan wählen → Probelauf ansehen | Neuer Pilot in unter 15 Minuten startklar |

Umsetzung F4 (M4-05): `/healthz` meldet einen ausgefallenen Worker mit HTTP 503, spätestens 5 Minuten nach dem letzten Lebenszeichen; strukturierte JSON-Logs ohne Inhalte; Fehlererfassung nur mit EU-Datenhaltung. Den externen Uptime-Check richtet das Team im Echtlauf ein.

Umsetzung F6 (M4-03): Seite „Einrichtung“ (`/einrichtung/`, nur Inhaber) mit vier Schritten und Status. Schritt 2 führt zur Liste „Kundentyp festlegen“; der Lexware-Hinweis Firma/Person wird nicht automatisch übernommen (Mahnlogik-und-Recht.md). Schritt 3 bietet drei Vorlagen (Freundlich, Standard, Konsequent), jede hält den Mindestabstand von 7 Tagen; Speichern unter Einstellungen zählt ebenfalls. Schritt 4 zeigt den Probelauf mit derselben Berechnung wie der Vorschlagslauf, ohne etwas zu speichern oder zu senden. Ob ein Pilot in unter 15 Minuten startklar ist, wird erst im Pilot gemessen.

Umsetzung F1 (M4-01): Abschnitt der Sammelfreigabe-Mail und Seite „Berichte“. „Eingegangen“ ist der Bruttobetrag der in den letzten 7 Tagen vollständig bezahlten Rechnungen laut Lexware; Teilzahlungen auf weiterhin offene Rechnungen zählen dort nicht mit (offene Frage).

## H. Import aus Excel (Meilenstein 6, vor dem Pilot)

Entscheidung in ADR-008. Gilt nur für Betriebe mit Lexware Office.

| ID | Anforderung | Abnahme |
| --- | --- | --- |
| H1 MUSS | Upload von Excel (`.xlsx`) und CSV mit Kopfzeile; Tabellenblatt wählbar; Zahlen, Beträge und Daten in deutschem Format | Beispieldateien aus Excel (Semikolon, Dezimalkomma, `TT.MM.JJJJ`) werden korrekt gelesen |
| H2 MUSS | Spaltenzuordnung mit Vorschlägen aus den Spaltennamen, vom Nutzer änderbar; Vorlagen zum Herunterladen | Vorlagen werden ohne Änderung vollständig zugeordnet |
| H3 MUSS | Vorschau vor jedem Import: neue Einträge, Dubletten (schon in Lexware oder im Cockpit), fehlerhafte Zeilen mit Grund | Nichts wird ohne Vorschau und Freigabe angelegt |
| H4 MUSS | Kunden werden nach Freigabe durch Inhaber oder Freigeber in Lexware angelegt (Firma oder Person, E-Mail, Rechnungsadresse); der Kundentyp aus Excel wird nur nach ausdrücklicher Bestätigung übernommen | Kontakt erscheint in Lexware und danach im Cockpit; keine Dubletten |
| H5 MUSS | Artikel werden nach Freigabe in Lexware angelegt (Bezeichnung, Art, Einheit, Nettopreis, Steuersatz 0, 7 oder 19 %) | Artikel steht danach für die Erfassung zur Verfügung |
| H6 MUSS | Alte offene Rechnungen werden nur im Cockpit geführt (Quelle „Import“), nie in Lexware gebucht; Kunde muss in Lexware existieren | Posten erscheinen in Cockpit und Postenliste, der Lexware-Abgleich verändert sie nicht |
| H7 MUSS | Zahlstatus importierter Posten pflegt der Betrieb im Cockpit: bezahlt mit Datum oder neuer offener Betrag; protokolliert | Bezahlte Posten erscheinen nicht mehr als offen und werden nicht gemahnt |
| H8 MUSS | Mahnwesen für importierte Posten nach denselben Regeln; Versand prüft den Zahlstatus im Cockpit; Mahnschreiben-PDF (Stufe 1 und 2, Postversand) erzeugt die App; Freigabe weist auf den manuell gepflegten Zahlstatus hin | Mahnung zu einem importierten Posten geht mit PDF der App hinaus; bezahlt markierte Posten werden nicht versendet |
| H9 MUSS | Jeder Import und jede Freigabe wird protokolliert; die Importdatei wird wie Rohdateien nach 7 Tagen gelöscht | Protokoll zeigt Datei, Anzahl und Ergebnis |

## I. Rückmeldung Lukas (Meilenstein 7)

Rückmeldung vom 5. November 2026, Entscheidungen von Yannick am selben Tag. Die großen Punkte (Abo-Verwaltung, Team-Chat, KI-Hilfe-Chat, KI-Telefonassistent) stehen als Konzept in [[Konzept-Erweiterungen]].

| ID | Anforderung | Abnahme |
| --- | --- | --- |
| I1 MUSS | Menüpunkt „Erfassen“ heißt „Angebote & Rechnungen“: neu erstellen per Sprache, Foto oder Mail, Entwürfe in Arbeit, offene Angebote mit Gültigkeit | Menü, Titel und Texte umbenannt; Angebote mit „gültig bis“ sichtbar |
| I2 MUSS | Cockpit mit Reitern: Überblick, Rechnungen, Angebote, Mahnungen; je Reiter Kennzahlen und eine kurze Liste mit Sprung zur Detailseite | Reiter über Links (ohne JavaScript), auf dem Handy bedienbar |
| I3 MUSS | „Berichte“ heißt „Statistik“, umschaltbar Woche und Monat; zusätzlich Angebote: verschickt, angenommen, abgelehnt, abgelaufen, Annahmequote, Volumen | Zahlen stimmen mit dem Spiegel überein (Tests) |
| I4 MUSS | Erinnerung an Angebote kurz vor Ablauf an den Endkunden, nur nach Freigabe (ADR-009) | Kein Versand ohne Freigabe; Frische-Check verwirft angenommene, abgelehnte und abgelaufene Angebote |
| I5 SOLL | Profil-Menü mit eigenem Avatar je Teammitglied (spielerische Symbole), Zugang zu Profil, Sicherheit, Team und Abmelden; „Abo und Zahlung“ als angekündigter Punkt | Avatar wählbar, in Seitenleiste und Team-Liste sichtbar |
| I6 SOLL | Hinweis zur E-Rechnung: Lexware erzeugt E-Rechnungen beim Abschließen; Pflichten nach Kundentyp und Datum verständlich erklärt | Hinweis bei Rechnungsentwürfen an Unternehmer und in den Lexware-Einstellungen |
| I7 – | PDF im Anhang: Erinnerungen tragen die Rechnung, Mahnungen das Mahnungs-PDF aus Lexware, Angebots-Erinnerungen das Angebots-PDF | bereits umgesetzt (D7, M2-05) bzw. mit I4 |

## J. KI-Telefonassistent (Meilenstein 8, Prototyp)

Entscheidung in ADR-010. Live-Gespräch, nur Rückruf-Notizen, kein Kalender. Im Pilot für alle Betriebe einschaltbar.

| ID | Anforderung | Abnahme |
| --- | --- | --- |
| J1 MUSS | Feste Ansage mit Pflichthinweis (digitaler Assistent, Umwandlung in Text und Speicherung, Auflegen möglich, Notruf 112); Begrüßung je Betrieb anpassbar | Pflichthinweis lässt sich nicht entfernen (Test) |
| J2 MUSS | Gesprächsführung erfragt Name, Anliegen, Rückrufnummer (bestätigt die übertragene Nummer), Dringlichkeit, ggf. beste Rückrufzeit; höchstens 8 Runden | Gespräch endet mit fester Verabschiedung und einer Rückruf-Notiz |
| J3 MUSS | KI nennt keine Preise, sagt keine Termine zu, berät nicht; im Code geprüft | Antwort mit „€“ oder Terminzusage wird ersetzt (Test) |
| J4 MUSS | Ausfallbetrieb ohne KI mit festen Fragen; aufgelegte Anrufe als „Anruf ohne Nachricht“ | Notiz entsteht auch bei KI-Fehler oder Limit |
| J5 MUSS | Rückruf-Notizen: Liste mit Dringlichkeit, Detail mit Verlauf, „erledigt“ mit Notiz; Mail an das Team nur mit Name, Dringlichkeit und Link | Protokoll für Anlage und Erledigung |
| J6 MUSS | Testanruf im Browser (Text und Mikrofon), gleiche Gesprächsführung, Kennzeichen „Test“ | Funktioniert ohne Telefonie |
| J7 MUSS | Telefonie: Anmeldung des Anrufs durch Asterisk per HTTPS mit Geheimnis; Audio über AudioSocket; Spracherkennung je Beitrag (Voxtral), Sprachausgabe Voxtral TTS (EU; Piper nur mit gewerblich freigegebener Stimme); eigenes Monatslimit je Firma, getrennt vom KI-Limit der Erfassung; Zuordnung der Firma über die angerufene Nummer | Simulierter Anruf über AudioSocket im Test ergibt Rückruf-Notiz |
| J8 MUSS | Löschfristen: Verlauf 90 Tage, Notizen 90 Tage nach Erledigung bzw. 12 Monate | im Löschjob mit Test |

## G. sevdesk (Meilenstein 5)

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| G1 KANN | Gleiche Funktionen wie B für sevdesk über eine gemeinsame Adapter-Schnittstelle | Cockpit und Mahnautomatik laufen unverändert gegen beide Adapter |
