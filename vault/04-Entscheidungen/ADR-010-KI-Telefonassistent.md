# ADR-010: KI-Telefonassistent für verpasste Anrufe (Live-Gespräch, nur Rückruf-Notizen)

Status: angenommen als **Prototyp** · 5. November 2026 · ergänzt ADR-004, ADR-005 und ADR-006

## Kontext
Rückmeldung von Lukas (Punkt 10): Verpasste Anrufe soll eine KI annehmen. Sie sammelt nur die wichtigsten Angaben für einen Rückruf: Name, Anliegen, Rückrufnummer und Dringlichkeit. Eine Terminkalender-Anbindung gibt es **nicht**. Das Angebot ist als Zusatzumsatz gedacht. Yannick hat am 5. November 2026 entschieden:
- Es wird ein **Live-Gespräch mit KI**, keine reine Mailbox.
- Im Pilot ist es für alle Betriebe einschaltbar.

## Entscheidung
1. **Telefonie in Deutschland, keine US-Plattform.**
   - Die Anrufe kommen über einen SIP-Trunk eines deutschen Anbieters auf eine eigene Telefonanlage (Asterisk) auf unserem Server in Deutschland.
   - Asterisk meldet jeden Anruf per HTTPS bei Belegfluss an. Dabei übergibt es die gewählte Nummer und die Nummer des Anrufers.
   - Dann streamt Asterisk das Audio über AudioSocket an den Belegfluss-Dienst: 16 Bit, 8 kHz, 20-ms-Pakete.
   - Twilio, Vonage, Vapi, Retell und ähnliche Dienste scheiden aus (ADR-005).
2. **Spracherkennung** mit Mistral Voxtral (EU) je Gesprächsbeitrag. **Dialog** mit Claude über Bedrock eu-central-1 (EU-Profil). **Sprachausgabe** mit Mistral Voxtral TTS (EU), siehe Ergänzung unten. Kein Audio verlässt die EU, und Audio wird nicht gespeichert.
3. **Feste Ansage vor jedem Gespräch, nicht von der KI formuliert.**
   - Die Ansage nennt den Betrieb und sagt, dass hier ein digitaler Assistent spricht.
   - Sie sagt, dass das Gespräch automatisch in Text umgewandelt und gespeichert wird, und dass man auflegen kann.
   - Sie verweist für Notfälle auf die 112.

   Die Begrüßung ist je Betrieb anpassbar, der Pflichthinweis nicht.
4. **Grenzen der KI**, im Prompt vorgegeben **und** im Code geprüft:
   - Sie nennt keine Preise und sagt keine Termine zu.
   - Sie gibt keine Fach-, Rechts- oder Steuerberatung.
   - Antworten mit Beträgen oder Terminzusagen werden durch einen festen Satz ersetzt.
   - Höchstens 8 Gesprächsrunden und 4 Minuten.
5. **Ergebnis ist nur eine interne Rückruf-Notiz.**
   - Das Team wird per Mail benachrichtigt. Die Mail enthält nur Name, Dringlichkeit und einen Link.
   - Nach außen geht nichts. Der Rückruf ist Sache des Betriebs.
6. **Ausfallsicher.** Ist die KI nicht erreichbar oder das Monatslimit erreicht, fragt der Assistent mit festen Sätzen nach Name, Anliegen und Rückrufnummer. Die Rückruf-Notiz entsteht trotzdem, dann mit dem Wortlaut statt einer Zusammenfassung. Legt der Anrufer vorher auf, entsteht eine Notiz „Anruf ohne Nachricht“ mit seiner Nummer, falls diese übertragen wurde.
7. **Löschfristen.**
   - Der Gesprächsverlauf wird 90 Tage nach dem Gespräch gelöscht.
   - Rückruf-Notizen werden 90 Tage nach „erledigt“ gelöscht, offene spätestens nach 12 Monaten.
   - Die Löschung wird protokolliert.
8. **Testanruf im Browser.** Der Betrieb kann den Assistenten ohne Telefon ausprobieren, per Text oder Mikrofon. Die Sprachausgabe übernimmt dabei nur eine lokale Stimme des Browsers.

## Folgen
+ Kein verpasster Anruf mehr, und das Team sieht Rückrufe gesammelt mit Dringlichkeit.
+ Alles läuft in Deutschland bzw. der EU, und der Anbieter ist austauschbar (SIP-Standard).
- Eigene Telefonanlage: Betrieb, Überwachung und Updates von Asterisk liegen bei uns (Betriebshandbuch).
- Die Antwortzeit liegt bei 2 bis 4 Sekunden je Runde, weil Spracherkennung, KI und Sprachausgabe nacheinander laufen. Für Rückruf-Notizen reicht das; ein flüssiges Verkaufsgespräch ist es nicht.
- **Vor dem ersten echten Anruf** sind nötig:
  - die rechtliche Prüfung (Ansage, § 201 StGB, DSGVO-Informationen, AVV mit Telefonie-Anbieter, Mistral und AWS),
  - ein SIP-Trunk mit Rufnummer,
  - die Installation von Asterisk und des Dienstes `telefon_dienst`,
  - ein Test mit echten Anrufen.

## Ergänzung 5. November 2026 (M8-06, Kostenkalkulation)
1. **Sprachausgabe: Voxtral TTS statt Piper als Standard.** Die naheliegende deutsche Piper-Stimme „thorsten“ beruht auf einem Datensatz, der nur für Forschung lizenziert ist. Konservativ nutzen wir sie nicht. Standard ist Mistral Voxtral TTS 3 (EU, Stimme „Heidi“, 13 $ je 1 Mio. Zeichen, ca. 0,6 ct je Anruf). Piper bleibt wählbar (`TELEFON_SPRACHAUSGABE=piper`), aber nur mit einer Stimme, deren gewerbliche Nutzung geklärt ist. Feste Sätze (Ansage, Verabschiedung) hält der Dienst im Speicher; Antworten der KI nie.
   - Folge: Die Antworten des Assistenten (Text) gehen an Mistral in der EU. Das ist derselbe Anbieter und dieselbe Datenhaltung wie bei der Spracherkennung (ADR-005).
2. **Modell: Claude Haiku 5.5 über das EU-Profil** (`TELEFON_MODELL=eu.anthropic.claude-haiku-5-5`), mit abgeschaltetem Mitdenken für kurze Antwortzeiten. Ein Systemcheck erlaubt nur `eu.`-Profile.
3. **Eigenes Limit.** Das Telefon zählt nicht mehr gegen das KI-Limit der Erfassung, sonst hätten 60 Anrufe im Monat die Belegerfassung blockiert. Es gilt `TELEFON_LIMIT_GESPRAECHE_MONAT` (Standard 400); darüber Ausfallbetrieb ohne KI. Die Token stehen je Gespräch.
4. **Telefonie-Anbieter:** easybell SIP-Trunk Business 10 mit Rufnummernblock im Ortsnetz unseres Sitzes (BNetzA-Verfügung 25/2006), Server Hetzner AX41 in Falkenstein. Begründung und Zahlen: [[Kostenkalkulation-Telefonassistent]].
