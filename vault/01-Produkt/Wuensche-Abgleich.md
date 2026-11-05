# Abgleich mit den Wünschen von Yannick und Lukas

Quellen: WhatsApp-Chat vom 4. November 2026, Lukas' Repository `belegfluss` (README, Wettbewerbsanalyse vom 3. November 2026, Landingpages), Konzeptdokument.

## Wünsche von Lukas

| Wunsch | Herkunft | Umsetzung |
| --- | --- | --- |
| B2B-Software, die im Alltag hilft, vor allem bei Handwerkern und anderen Dienstleistern | Chat | Zielgruppe des Produkts |
| Erleichterung im Rechnungswesen, Angebots- und Rechnungserstellung | Chat | Erfassung E1–E9 erzeugt Angebots- und Rechnungsentwürfe; Mahnautomatik D |
| Kein eigenes Rechnungsprogramm, Schicht über Lexware/sevdesk | Wettbewerbsanalyse | ADR-001, Kern der Architektur |
| KI erstellt nur Entwürfe, Freigabe durch den Geschäftsführer | Belegfluss README | ADR-004, D6, E7 |
| KI legt nie Preise, Steuern oder Nummern fest; feste Regeln rechnen | Belegfluss README | E4, E5; Regel-Engine aus Belegfluss übernehmbar |
| Mehrere Quellen pro Beleg: Mail, Zeiterfassung (CSV), Sprachmemo | Belegfluss | E1, E2; CSV-Zeiterfassung als Quelle |
| Mehraufwand gegenüber Angebot sichtbar machen | Belegfluss | E10 (SOLL) |
| Freigabe auch unterwegs, per Mail-Link oder WhatsApp | Belegfluss-Landingpage | Mail-Link mit Login (D6); WhatsApp später (E11) |
| EU-Verarbeitung, Mistral Voxtral für Sprache, Claude über Bedrock Frankfurt | Belegfluss | ADR-005 |
| Hosting bei Hetzner in Deutschland, Zwei-Faktor, Rollen | Belegfluss | A2, A3, Betrieb |
| Start als Dienstleistung mit Einrichtungsgebühr | Wettbewerbsanalyse | Onboarding F6 und Einrichtung durch das Team; Preis außerhalb der App |
| Microsoft-365-Postfach als Eingang | Belegfluss | KANN; MVP nutzt Weiterleitung an eine eigene Belegadresse |
| Nutzung seines Codes freigegeben, aber eigener Workflow von Grund auf gewünscht | Gespräch 5. November 2026 | ADR-007 |

## Wünsche von Yannick

| Wunsch | Herkunft | Umsetzung |
| --- | --- | --- |
| Ähnlich wie ein ERP, aber viel einfacher | Chat | Bewusst nur drei Funktionen, kein ERP-Umfang |
| Optisch mit einem Dashboard der offenen Rechnungen und Forderungen | Chat | Forderungs-Cockpit C1–C6 ist die Startseite und das Kernprodukt |
| Eventuell mit einem CRM gekoppelt | Chat | Kundenansicht C3 mit Zahlungsverhalten; echtes CRM bewusst nicht im MVP |
| Audiovisuell schnell Rechnungen verfassen; KI-Agent plant und erstellt Rechnungen | Chat | E1–E9 als Entwurf mit Freigabe; "selbständig versenden" bewusst ausgeschlossen (Haftung § 14c UStG) |
| Kann komplett anders aufgebaut sein als Belegfluss | Chat | Neues Repository, Eigenbau von Grund auf; Belegfluss als Orientierung (ADR-007) |

## Ausdrücklich verworfen und warum

- **Autonomer Versand von Rechnungen:** Der Betrieb haftet für jeden falschen Steuerausweis; kein Wettbewerber macht das.
- **Eigene E-Rechnung und Nummernkreise:** Liegt beim zertifizierten Bestandstool, spart Wochen und Haftung.
- **Solo-Handwerker-Sprach-App:** Mindestens sieben Konkurrenten, Preis 0 bis 39 €, hoher Churn.
