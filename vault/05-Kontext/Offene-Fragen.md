# Offene Fragen

Agenten tragen hier ein, was sie nicht aus dem Vault beantworten können, mit Datum und getroffener Annahme.

| Datum | Frage | Annahme bis zur Klärung | Wer klärt |
| --- | --- | --- | --- |
| 2026-11-05 | Hat die 4-Wochen-Validierung stattgefunden, und hat Keil A gewonnen? | Bau beginnt trotzdem mit M0 bis M1, weil das Cockpit für beide Keile nützt | Yannick, Lukas |
| 2026-11-05 | ~~Darf Code aus Belegfluss übernommen werden?~~ **Geklärt am 2026-11-05:** Lukas stimmt zu. Gebaut wird trotzdem von Grund auf, Belegfluss ist Orientierung; Übernahme nur nach ADR-007 | erledigt | Lukas |
| 2026-11-05 | ~~Request-Body der Lexware-Mahnung (Gebühren, Zinsen, Einleitung)~~ **Doku geprüft am 2026-11-05:** `lineItems` unterstützt `custom` und `text`; das offizielle Beispiel zeigt eine `custom`-Position mit 0 % bei `taxType net`. Umsetzung: Textposition mit offenem Betrag, Zinsen und Pauschale als `custom` mit 0 %, zusätzlich im Mailtext. **Offen für den Echtlauf:** Akzeptiert Lexware eine Mahnung, die nur eine Textposition enthält (Stufe ohne Zinsen)? | bis zum Echtlauf: so umgesetzt; lehnt Lexware ab, landet der Vorschlag sichtbar auf "Fehler" mit Neuversuch | Entwickler, Echtlauf |
| 2026-11-05 | ~~Signaturprüfung der Lexware-Webhooks (Header, Schlüssel)~~ **Geklärt am 2026-11-05:** `X-Lxo-Signature`, RSA-SHA512 über den JSON-Body, öffentlicher Schlüssel aus der Doku | erledigt (Umsetzung M1-08) | Entwickler |
| 2026-11-05 | Welches Claude-Modell ist in `eu-central-1` per EU-Profil verfügbar? | konfigurierbar, aktuellstes verfügbares Sonnet | Entwickler |
| 2026-11-05 | Welcher EU-SMTP-Anbieter (Zustellbarkeit, Bounce-Webhooks, AVV)? | Anbieter mit EU-Sitz und AVV wählen, Entscheidung als ADR festhalten | Team |
| 2026-11-05 | Produktname und Domain | Arbeitstitel "Cockpit", Paketname `cockpit` | Team |
| 2026-11-05 | Mahntexte und Zinslogik rechtlich geprüft? | nein; vor erstem Pilot durch Anwalt/Steuerberater (M4-07) | Team |
| 2026-11-05 | Der Token-Bucket (2 Anfragen/s) gilt je Prozess. Web (nur Schlüsseltest) und Worker teilen ihn nicht. Reicht das? | Ja für einen Worker-Prozess; 429 werden zusätzlich mit Backoff wiederholt. Bei mehreren Workern Bucket in Postgres verlagern | Entwickler |
| 2026-11-05 | Bezieht sich die Altersstruktur (C1) auf Tage seit Rechnungsdatum oder Tage überfällig? | Tage überfällig (ab Fälligkeit), nicht fällige Posten getrennt; das ist die übliche Forderungs-Altersstruktur | Yannick |
| 2026-11-05 | Prognose (C4): Wie mit Posten umgehen, deren erwarteter Termin schon vorbei ist? | Nicht in die Wochen einrechnen, sondern getrennt als „Termin unsicher“ zeigen (vorsichtige Liquiditätsplanung) | Yannick |
