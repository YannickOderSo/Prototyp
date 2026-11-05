# Konzept: große Punkte aus Lukas' Rückmeldung

Stand: 5. November 2026 · Status: **Konzept, nicht gebaut** · Entscheidung von Yannick: erst die schnellen Punkte (M7), diese vier Punkte als Grundlage für die Planung nach dem Pilot.

Für jeden Punkt gilt: Daten nur in der EU (ADR-005), nichts mit Außenwirkung ohne Freigabe (ADR-004), Protokoll für jeden Schritt mit Außenwirkung. Preise und Anbieter sind **nicht geprüft**, solange es nicht dabeisteht. Vor einer Entscheidung wird je Punkt ein eigenes ADR geschrieben.

## Überblick

| Punkt | Nutzen | Aufwand (Schätzung) | Empfehlung |
| --- | --- | --- | --- |
| Abo und Zahlung im Profil (Punkt 2) | Kunden verwalten Tarif, Kündigungsfrist und Zahlungsmittel selbst | 6–8 PT | vor dem Verkauf an mehr als die Pilotbetriebe |
| Team-Chat (Punkt 3) | Absprachen im Team ohne WhatsApp | Notizen an Belegen 3–4 PT, echter Chat 8–12 PT | zuerst Notizen mit @-Erwähnung an Kunden, Belegen und Angeboten |
| KI-Hilfe-Chat (Punkt 9) | Weniger Support-Anrufe | 4–5 PT | nach dem Pilot, mit Hilfe-Artikeln als einziger Quelle |
| KI-Telefonassistent (Punkt 10) | Kein verpasster Anruf, Zusatzumsatz | 10–15 PT für eine „intelligente Mailbox“ | eigenes Zusatzmodul nach dem Pilot; rechtliche Prüfung zuerst |

## 1. Abo und Zahlung im Profil

**Ziel:** Unter dem Profil-Symbol findet der Inhaber:
- Tarif und Preis,
- nächste Abrechnung und Kündigungsfrist, mit Kündigungsknopf (Kündigungsbutton nach § 312k BGB prüfen, gilt für Verbraucherverträge; unsere Kunden sind Unternehmer, trotzdem fair anbieten),
- Zahlungsmittel ändern,
- Rechnungen von uns herunterladen.

**Bausteine:**
- Zahlungsanbieter mit Sitz und Datenverarbeitung in der EU. Kandidat: Mollie (Niederlande, SEPA-Lastschrift und Karte, Abo-Schnittstelle). Stripe hat einen US-Mutterkonzern, das ist nach ADR-005 zu prüfen. Beides **nicht geprüft**.
- Zahlungsdaten erfasst nur die gehostete Seite des Anbieters, nie die App (keine Kartendaten bei uns).
- Unsere eigenen Rechnungen schreiben wir in **unserem** Lexware Office. Kein eigenes Rechnungsprogramm in der App (ADR-001 gilt auch für uns).
- Webhook des Anbieters: Zahlung fehlgeschlagen → Hinweis an den Inhaber, nach Frist Zugang nur lesend. Nie Daten löschen wegen Zahlungsverzug.

**Offene Fragen:**
- Tarife (49 bis 99 € laut Konzept) und Laufzeit: monatlich oder jährlich?
- Kündigungsfrist.
- Gibt es eine Testphase?

## 2. Team-Chat

**Ziel:** Absprachen im Betrieb, z. B. „Kunde Weber zahlt nächste Woche“ oder „Angebot Praxis Sommer bitte prüfen“.

**Empfehlung, Stufe 1:** Notizen mit @-Erwähnung direkt an Kunde, Rechnung, Angebot und Mahnvorschlag.
- Die Erwähnung erzeugt einen Hinweis in der App und optional eine Mail.
- Das deckt die meisten Fälle ab, ohne neue Technik (kein Websocket, kein Redis) und mit klarem Bezug zum Vorgang.

**Stufe 2:** Echter Chat je Firma.
- Nötig sind Django Channels und Redis, Lesestatus, Push auf dem Handy, Moderation und Löschfristen.
- Konkurrenz: WhatsApp, Signal und Teams sind im Betrieb meist schon da. Der Mehrwert liegt im Bezug auf Belege, nicht im Chat selbst.

**Datenschutz:** Chatinhalte sind Beschäftigtendaten. Es braucht Löschfristen, und eine Leistungskontrolle ist auszuschließen. Bei Betrieben mit Betriebsrat ist eine Mitbestimmung möglich.

## 3. KI-Hilfe-Chat

**Ziel:** Handwerker fragen in der App „Wie lege ich einen Kundentyp fest?“ statt anzurufen.

**Umfang Stufe 1:**
- **Quelle:** Die KI antwortet nur aus unseren Hilfe-Artikeln, Markdown im Repository wie die Rechtstexte. Bei fehlender Antwort sagt sie „weiß ich nicht“ und bietet den Kontakt zum Support an.
- **Modell:** Claude über Bedrock, EU-Profil (ADR-005). Kein Zugriff auf Kunden- oder Belegdaten der Firma in Stufe 1. Das ist einfacher beim Datenschutz und schließt Fehlhandlungen aus.
- **Grenzen:**
  - Keine Rechts- und Steuerberatung, z. B. zu Mahnfristen im Einzelfall oder zur Umsatzsteuer. Dazu ein fester Hinweis.
  - Keine Aktionen: Die KI erzeugt nur Antworten, nichts verlässt die App (CLAUDE.md).
- **Kosten:** etwa 0,01 bis 0,03 € je Frage (Schätzung nach den Bedrock-Preisen in der Kostenkalkulation). Begrenzt durch das vorhandene KI-Limit je Firma.
- **Protokoll:** Frage und Antwort 30 Tage zur Qualitätsprüfung, danach gelöscht. Eine Nutzerangabe ist dafür nicht nötig.

## 4. KI-Telefonassistent

**Ziel (Lukas):** verpasste Anrufe annehmen und die wichtigsten Angaben aufnehmen: Name, Anliegen, Rückrufnummer, Dringlichkeit. **Keine** Terminkalender-Anbindung, nur Notizen für den Rückruf. Upsell für etwa 50 € im Monat.

**Empfehlung, Stufe 1 „intelligente Mailbox“:**
1. Rufumleitung bei Nichtannahme auf eine Rufnummer des Assistenten.
2. Feste Ansage (aufgezeichnet, keine KI-Stimme nötig). Sie nennt den Betrieb, kündigt die automatische Verarbeitung an und bittet um Name, Anliegen und Rückrufnummer.
3. Aufnahme der Nachricht, danach Transkription (Mistral Voxtral, EU) und Zusammenfassung (Claude, Bedrock EU) zu einer **Rückruf-Notiz** in Belegfluss.
4. Hinweis per Push oder Mail an den Betrieb: „Rückruf: Frau Weber, Wasserschaden Küche, dringend, 0151 …“.
5. Audio wird nach der Transkription gelöscht wie heute bei Sprachmemos. Die Notiz folgt den Löschfristen.

**Stufe 2:** Ein echter Dialog mit Rückfragen (Spracherkennung, KI und Sprachausgabe in Echtzeit). Er ist deutlich teurer und fehleranfälliger. Erst wenn Stufe 1 angenommen wird.

**Rechtliches, vor dem Bau zu klären:**
- **§ 201 StGB** (Vertraulichkeit des Wortes) und DSGVO:
  - Die Aufnahme nur nach klarer Ansage am Anfang.
  - Wer weiterspricht, willigt ein. Ob das genügt, prüft der Anwalt.
  - Informationspflichten nach Art. 13 DSGVO in Kurzform in der Ansage, ausführlich auf der Website des Betriebs.
- **Telefonie-Anbieter mit Sitz und Verarbeitung in der EU** (Kandidat: ein deutscher VoIP-Anbieter mit Programmierschnittstelle; Twilio und Vonage sind US-Anbieter und scheiden nach ADR-005 aus). Anbieter, Funktionsumfang und Preise sind **nicht geprüft**.
- Rufnummern und Portierung, Notrufhinweis: Die Ansage muss sagen, dass hier kein Notruf möglich ist.

**Kosten je Betrieb (grobe Schätzung, nicht geprüft):**
- Rufnummer und Minuten beim Anbieter.
- Transkription: 0,0035 $ je Minute.
- Zusammenfassung: etwa 0,01 € je Anruf.

Bei 100 Anrufen im Monat liegt das deutlich unter 10 €. Ein Zusatzpreis von etwa 50 € trägt sich also, wenn die Telefoniekosten im üblichen Rahmen liegen.

## Nächste Schritte
1. Nach dem Pilot: Reihenfolge festlegen. Vorschlag: Notizen mit @-Erwähnung, dann KI-Hilfe-Chat, dann Abo-Verwaltung, dann Telefonassistent.
2. Je Punkt ein ADR mit geprüften Anbietern und Preisen.
3. Telefonassistent: zuerst rechtliche Prüfung (Ansage, Einwilligung, AVV), dann ein kleiner Test mit einem Pilotbetrieb.
