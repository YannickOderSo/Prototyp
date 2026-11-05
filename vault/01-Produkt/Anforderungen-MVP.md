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

## G. sevdesk (Meilenstein 5)

| ID | Anforderung | Abnahmekriterium |
| --- | --- | --- |
| G1 KANN | Gleiche Funktionen wie B für sevdesk über eine gemeinsame Adapter-Schnittstelle | Cockpit und Mahnautomatik laufen unverändert gegen beide Adapter |
