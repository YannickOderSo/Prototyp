# ADR-008: Import aus Excel – Stammdaten nach Lexware, alte offene Posten nur ins Cockpit

Status: angenommen · 5. November 2026 · ergänzt ADR-001, ADR-004 und ADR-006

## Kontext
Viele Betriebe haben Kunden, Preise und offene Rechnungen bisher in Excel geführt, auch nachdem sie Lexware Office eingeführt haben. Damit das Cockpit vom ersten Tag an vollständig ist, sollen diese Daten importiert werden können (Wunsch von Yannick und Lukas vom 5. November 2026).

Geprüft in der Lexware-Doku (5. November 2026):
- Kontakte (`POST /v1/contacts`) und Artikel (`POST /v1/articles`) lassen sich über die API anlegen. Die Kundennummer vergibt Lexware selbst.
- Rechnungen, die außerhalb von Lexware geschrieben wurden, kann Lexware nur als Buchungsbeleg (`salesinvoice`, `POST /v1/vouchers`) erfassen. Eine Lexware-Mahnung verlangt aber eine Lexware-Rechnung als Bezug. Ein Buchungsbeleg würde außerdem in die Buchhaltung eingehen und doppelt gebucht, wenn der Steuerberater die Rechnung schon erfasst hat.

## Entscheidung
1. **Nur für Betriebe mit Lexware Office.** Der Import hilft beim Umstieg; die App wird kein eigenes Rechnungsprogramm (ADR-001 bleibt).
2. **Kunden und Artikel gehen nach Lexware.** Die App legt sie über die API an, erst nach Vorschau und Freigabe durch Inhaber oder Freigeber mit zweitem Faktor (ADR-004). Bereits vorhandene Einträge werden nicht doppelt angelegt. Preise im Artikel-Import sind Angaben des Betriebs aus seiner eigenen Preisliste, keine KI-Ausgabe.
3. **Alte offene Rechnungen kommen nur ins Cockpit.** Sie werden als Posten mit Quelle „Import“ geführt, nicht in Lexware gebucht und vom Lexware-Abgleich ausgenommen. Den Zahlstatus pflegt der Betrieb im Cockpit („bezahlt“ oder neuer offener Betrag).
4. **Mahnwesen für importierte Posten ohne Lexware-Mahnung.** Vorschläge entstehen nach denselben Regeln (Mahnlogik-und-Recht.md). Statt des Frische-Checks in Lexware prüft der Versand den Zahlstatus im Cockpit, und die Freigabe-Liste weist darauf hin, dass der Zahlstatus von Hand gepflegt wird. Das Mahnschreiben (Stufe 1 und 2) und das PDF für den Postversand erzeugt die App selbst; eine Zahlungserinnerung geht ohne Anhang, weil die ursprüngliche Rechnung der App nicht vorliegt. Das Mahnschreiben ist keine Rechnung und trägt keine Rechnungsnummer der App.
5. **Formate:** Excel (`.xlsx`) und CSV. Spalten werden über Vorschläge zugeordnet und vom Nutzer bestätigt. Vorlagen zum Herunterladen.

## Folgen
+ Betriebe aus Excel sind am ersten Tag vollständig im Cockpit.
+ Keine Doppelbuchung in Lexware und keine Rechnungen außerhalb von Lexware.
- Für importierte Posten gibt es keinen automatischen Zahlungsabgleich; der Betrieb muss Zahlungen im Cockpit eintragen. Das Risiko einer Mahnung trotz Zahlung ist höher und wird in der Freigabe sichtbar gemacht.
- Die App erzeugt erstmals selbst ein PDF (Mahnschreiben). Inhalt und Form gehören zur rechtlichen Prüfung der Mahntexte (Prüfliste für das Team).
