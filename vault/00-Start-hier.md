# Start hier

**Produktname: Belegfluss** (entschieden am 5. November 2026, vorher Arbeitstitel „Forderungs- und Abrechnungs-Cockpit“). „Cockpit“ bleibt der Name der Übersichtsseite in der App. Logo und Farben: `web/static/web/logo/` und [[Konventionen]]. Nicht zu verwechseln mit Lukas' älterem Repository `belegfluss`: Für Code daraus gilt weiter [[ADR-007-Eigenbau-Belegfluss-als-Orientierung]].

Stand: 5. November 2026 · Autor: Yannick (mit Claude) · Status: bereit zum Bauen nach bestandener Validierung

## Worum es geht

Ein Web-Werkzeug für Handwerksbetriebe und kleine Dienstleister mit 3 bis 20 Mitarbeitern, die **Lexware Office** (später auch sevdesk) bereits nutzen. Es sitzt **auf** diesem Tool und erledigt drei Dinge, die das Tool nicht gut kann:

1. **Forderungs-Cockpit:** Wer schuldet uns wie viel, wie lange schon, was kommt die nächsten 4 Wochen rein?
2. **Mahnautomatik mit Freigabe:** Zahlungserinnerung, 1. und 2. Mahnung nach festen Regeln, Verzugszinsen und Pauschale korrekt nach Kundentyp, wöchentliche Sammelfreigabe, Versand per E-Mail.
3. **Erfassung per Sprache, Foto oder Mail:** Aus einem Sprachmemo, einem Foto (Stundenzettel, Lieferschein) oder einer weitergeleiteten Mail entsteht ein **Angebots- oder Rechnungsentwurf im Bestandstool**, den der Inhaber prüft und dort abschließt.

Dazu ein wöchentlicher Liquiditätsbericht per Mail.

## Warum so und nicht als eigenes ERP

Siehe `05-Kontext/Konzept-Zusammenfassung.md`. Kurz: Ein eigenes Rechnungsprogramm konkurriert frontal mit plancraft, HERO, ToolTime, Lexware und sevdesk. Lexware Office und sevdesk haben **kein automatisches Mahnwesen**. Ein Aufsatz vermeidet Systemwechsel, Steuerhaftung und GoBD-Last.

## Landkarte des Vaults

| Ordner | Inhalt |
| --- | --- |
| `01-Produkt/` | Vision, Personas, MVP-Anforderungen mit Abnahmekriterien, Abgleich mit Lukas' und Yannicks Wünschen |
| `02-Architektur/` | Architektur, Datenmodell, Lexware-Integration, KI-Pipeline, Mahnlogik und Recht, Sicherheit und Betrieb |
| `03-Umsetzung/` | Meilensteine und Tickets in Bau-Reihenfolge, Teststrategie, Konventionen, Fortschritt, Betriebshandbuch, Prüfliste für das Team, Datenschutz-Unterlagen und Ablauf bei Datenpannen (Entwürfe) |
| `04-Entscheidungen/` | Architecture Decision Records (bindend) |
| `05-Kontext/` | Konzept-Zusammenfassung, Lehren aus Belegfluss, offene Fragen, Glossar |

## Bau-Reihenfolge in einem Satz

M0 Gerüst → M1 Lexware lesen und Cockpit → M2 Mahnautomatik → M3 Erfassung per Sprache/Foto/Mail → M4 Wochenbericht, Onboarding, Härtung → M5 sevdesk. Details in `03-Umsetzung/Meilensteine-und-Tickets.md`.

## Definition of Done für das MVP

Ein Pilotbetrieb mit Lexware Office XL kann sich anmelden, seinen Lexware-Schlüssel hinterlegen, sieht innerhalb von 2 Minuten seine offenen Posten nach Alter, gibt montags die vorgeschlagenen Erinnerungen und Mahnungen frei, und diese gehen korrekt als E-Mail mit PDF an seine Kunden. Er kann ein Sprachmemo aufnehmen und findet danach einen Rechnungsentwurf in Lexware. Alles ist protokolliert, läuft auf einem Server in Deutschland und ist mit automatischen Tests abgedeckt.
