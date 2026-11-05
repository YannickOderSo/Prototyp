# ADR-009: Erinnerung an Angebote kurz vor Ablauf, an den Endkunden nach Freigabe

Status: angenommen · 5. November 2026 · ergänzt ADR-004 und ADR-006

## Kontext
Lukas' Rückmeldung vom 5. November 2026: Angebote verlaufen oft im Leeren. Der Betrieb möchte vor Ablauf eine Rückmeldung seines Kunden. Yannick hat entschieden, dass die Erinnerung an den Endkunden geht, und zwar erst nach Freigabe.

Geprüft in der Lexware-Doku am 5. November 2026:
- Angebote haben `expirationDate` (`GET /v1/quotations/{id}`).
- Status in der Belegliste: `open`, `accepted` und `rejected`.
- Das PDF liefert `GET /v1/quotations/{id}/file`. Für Entwürfe gibt es keines (409).

## Entscheidung
1. **Vorschlag statt Automatik.** Ein täglicher Lauf schlägt für jedes offene Angebot eine Erinnerung vor, wenn:
   - der Ablauf in höchstens X Tagen bevorsteht (Standard 7, damit die wöchentliche Sammelfreigabe die Erinnerung rechtzeitig erfasst; je Firma einstellbar von 1 bis 30),
   - der Kunde eine E-Mail-Adresse hat,
   - für dieses Angebot noch keine Erinnerung vorgeschlagen wurde.

   Je Angebot gibt es höchstens eine Erinnerung.
2. **Freigabe wie bei Mahnungen.** Freigeben dürfen nur Inhaber oder Freigeber, angemeldet und mit zweitem Faktor. Ein Link in einer Mail gibt nie frei (ADR-004).
3. **Frische-Check vor dem Versand.** Vor dem Versand liest die App das Angebot erneut aus Lexware.
   - Ist es angenommen, abgelehnt, gelöscht oder schon abgelaufen, wird der Vorschlag verworfen und nichts gesendet.
4. **Versand durch die App (ADR-006).**
   - Die Mail ist freundlich und ohne Druck: Bezug auf Angebot, Datum und Gültigkeit, Bitte um kurze Rückmeldung.
   - Absendername und Antwortadresse sind die des Betriebs.
   - Im Anhang liegt das Angebots-PDF aus Lexware.
   - Betreff und Text sind je Firma im Mahnplan einstellbar. Dort lässt sich die Funktion auch abschalten.
5. **Protokoll** für Vorschlag, Freigabe, Frische-Check und Versand.

## Folgen
+ Der Betrieb bekommt Rückmeldungen auf Angebote, ohne selbst nachzuhalten.
+ Gleicher Sicherheitsweg wie bei Mahnungen: nichts ohne Freigabe.
- Ein weiterer Mailtyp an Endkunden. Zustellbarkeit und Ton gehören zur Prüfung der Texte (Prüfliste für das Team).
- Für Angebote spiegelt die App jetzt auch die Status „angenommen“ und „abgelehnt“ und das Ablaufdatum. Grundlage für die Angebotsstatistik.
