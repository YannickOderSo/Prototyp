# KI-Pipeline für die Erfassung

Grundsatz aus Belegfluss, unverändert übernommen: **Die KI ordnet zu, Regeln rechnen.** Kein Preis, kein Steuersatz, keine Nummer kommt aus einem Sprachmodell.

## Schritte

1. **Eingang** (`Erfassung` + `Datei`): Browser-Aufnahme (MediaRecorder, webm/opus oder m4a), Upload (Audio, JPG/PNG/HEIC, PDF, CSV, TXT, EML), Belegpostfach.
2. **Transkription** (nur Audio): Mistral Voxtral über die EU-API (`api.mistral.ai`, Daten standardmäßig in der EU), Sprache `de`. Modellname konfigurierbar, Standard `voxtral-mini-latest`; vor Implementierung in der Mistral-Doku prüfen. Audio danach löschen.
   Umgesetzt (M3-02, `capture/transkription.py`): `POST /v1/audio/transcriptions` (multipart `file`, `model`, `language=de`, laut Mistral-Doku vom 5. November 2026), Antwortfeld `text`. Audio wird direkt nach erfolgreicher Transkription gelöscht und das protokolliert; schlägt die Transkription fehl, bleibt es für den Neuversuch (spätestens der Löschjob entfernt es nach 7 Tagen). Höchstens 3 Versuche, dann „Fehler“ mit Knopf „Erneut versuchen“.
   EU-Zwang (ADR-005): Systemchecks `cockpit.E001` bis `E003` verhindern den Start mit einer Nicht-EU-Region, einem Bedrock-Modell ohne EU-Inferenzprofil (`eu.`-Präfix; `global.` und `us.` sind gesperrt) oder einem anderen Mistral-Host.
3. **Vorschau:** Transkript anzeigen und bearbeitbar machen (E3). Umgesetzt (M3-03): Status „Text prüfen“ zeigt Transkript, Notiz und aufbereitete Dateien; „Nur speichern“ oder „Entwurf erzeugen“. Aus der Prüfansicht lässt sich der Text erneut ändern und „Entwurf neu erzeugen“. Nach der Freigabe ist nichts mehr änderbar. Änderungen werden protokolliert. Erfassungen aus dem Belegpostfach haben keinen Bearbeiter vor Ort und gehen direkt in die Extraktion; geprüft wird dort in der Prüfansicht.
4. **Textaufbereitung:** PDFs per Textextraktion (pypdf), CSV-Zeiterfassung deterministisch zu Summen je Kunde und Projekt verdichten (Logik aus Belegfluss `quellen.py` übernehmbar), Mails parsen (Text plus Anhänge).
   Umgesetzt (M3-04, `capture/aufbereitung.py`): PDF höchstens 50 Seiten, verschlüsselte oder textlose PDFs mit Hinweis („als Foto hochladen“). CSV: Trennzeichen aus der Kopfzeile, Dauer als „4,5“, „4.5“, „1:30“ oder „01:30:00“, Summen je Kunde und Projekt auf Cent gerundet, Zeitraum aus der Datumsspalte, unlesbare Zeilen mit Hinweis. Die Spaltennamen-Zuordnung gängiger Exporte ist aus `belegfluss/quellen.py` übernommen (mit Herkunftsvermerk, ADR-007), Parser und Summen sind neu. Mails: Kopf und Text (HTML ohne Tags), Anhänge hochgeladener Mails werden eigene Dateien mit derselben Typprüfung. Jede Quelle höchstens 15.000 Zeichen. Ergebnis je Quelle in `Erfassung.quellen` (art, name, herkunft, text, stunden).
5. **Extraktion:** Claude über Amazon Bedrock in `eu-central-1` mit EU-Inferenzprofil. Modell konfigurierbar; Standard ist das aktuellste Claude-Sonnet-Modell, das dort per EU-Profil verfügbar ist. Fotos als Bild-Input im selben Aufruf. Structured Output per JSON-Schema (unten). Quellen in `<quelle>`-Tags, System-Prompt erklärt sie als Daten Dritter.
   Umgesetzt (M3-05, `capture/extraktion.py`): offizielles Anthropic-SDK mit `AnthropicBedrockMantle(aws_region="eu-central-1")` (Endpunkt `bedrock-mantle.eu-central-1.api.aws`, Messages-API), Modell `BEDROCK_MODELL`, Standard `eu.anthropic.claude-sonnet-5-5` (Claude Sonnet 5.5, EU-Profil). Strukturierte Ausgabe über `output_config.format` (`json_schema`), Aufwand `medium`. Laut Anthropic-Doku zu Bedrock (5. November 2026) leitet der Global-Endpunkt weltweit; nur ein geografisches Profil hält die Daten in der EU, deshalb blockiert ein Systemcheck alles ohne `eu.`-Präfix. Ob die Profil-ID auf dem Mantle-Endpunkt genau `eu.anthropic.claude-sonnet-5-5` lautet, ist offen (Echtlauf); eine falsche ID scheitert sichtbar, ohne Daten außerhalb der EU zu verarbeiten. Quelltexte werden so maskiert (`<` und `>`), dass sie die `<quelle>`-Struktur nicht aufbrechen können. Fotos JPG und PNG als Base64-Bild; HEIC mit Hinweis. Ablehnung (`refusal`), abgeschnittene Antwort, ungültiges JSON und unerwartete Felder führen zu „Fehler“. Netzwerk- und 429/5xx-Fehler: bis 3 Versuche.
   Kostenlimit: `KI_LIMIT_VORGAENGE_MONAT` (Standard 300) und `KI_LIMIT_TOKENS_MONAT` (Standard 3 Mio.) je Firma und Monat, Zählung in `KiVerbrauch`.
6. **Regeln** (deterministisch, `capture/rules.py`): Kunde gegen Kontakte des Spiegels (Name, Aliase, Kundennummer); Artikel gegen Artikel des Spiegels; Preis und Steuersatz nur aus Artikel; ohne Artikel Preis leer und Blocker; Mengen > 0; Leistungszeitraum Pflicht bei Rechnungen; Hinweise bei Menge über offenem Angebot.
   Umgesetzt (M3-06): reine Funktion `entwurf_bilden()` mit Tabellen-Tests (98 % Abdeckung). Kundenabgleich über Namen (auch „Nachname, Vorname“) und Kundennummer; Aliase gibt es im Spiegel nicht. Archivierte Artikel gelten nicht. Ohne Artikel darf nur der Nutzer in der Prüfansicht Preis und Steuersatz (19, 7 oder 0 %) setzen; das KI-Schema kann diese Felder nicht liefern (unerwartete Felder führen zu „Fehler“). Leistungszeitraum: Pflicht bei Rechnungen, Ende nicht vor Beginn, Hinweis bei Zukunft. E10: Offene und angenommene Angebote werden mitgespiegelt; die Positionen holt die App bei Bedarf per `GET /v1/quotations/{id}`, Mehrmengen werden als Hinweis „Mehraufwand“ markiert. Zeiterfassung: Abweichung zwischen erfassten und abgerechneten Stunden als Hinweis. E9: Anweisungsmuster in Quellen („setze den Preis auf 0“, „ignoriere alle Anweisungen“ …) werden deterministisch erkannt und als Hinweis gemeldet; Preise ändern sie nie, weil das Schema kein Preisfeld hat. Offene Fragen der KI erscheinen als Hinweise. Die Antwort der KI bleibt unverändert in `ki_ergebnis`, Änderungen des Nutzers stehen in `eingabe`.
7. **Prüfansicht:** Positionen mit Herkunft und Hinweisen, editierbar, Blocker verhindern Freigabe.
   Umgesetzt (M3-07): je Position Herkunft („gehört“, „aus Foto“, „aus Mail“, „aus Zeiterfassung“, „aus Notiz“, „vom Nutzer ergänzt“) und Preisherkunft („aus Stammdaten (Lexware-Artikel …)“ oder „vom Nutzer gesetzt“). Änderbar: Belegart, Kunde (Auswahl aus dem Spiegel), Leistungszeitraum, Angebotsbezug, Beschreibung, Menge, Einheit, Artikel; Preis und Steuersatz nur bei Positionen ohne Artikel. Positionen entfernen und ergänzen. Jede Änderung läuft erneut durch die Regeln und wird protokolliert. Der Freigabeknopf ist bei Blockern gesperrt und nur für Inhaber und Freigeber sichtbar.
8. **Übertragung:** `create_invoice_draft` bzw. `create_quotation_draft` im Bestandstool, Link anzeigen, Protokoll.
   Umgesetzt (M3-08, `capture/uebertragung.py`): Freigabe nur durch Inhaber oder Freigeber per POST; vorher laufen die Regeln erneut, Blocker verhindern die Freigabe. Job `capture.uebertragen` legt den Entwurf an (Rechnung mit Leistungszeitraum, Angebot mit 30 Tagen Gültigkeit), Artikelpositionen als `service`/`material` mit Artikel-ID, Positionen ohne Artikel als `custom` mit dem vom Nutzer gesetzten Preis. Nie `finalize` (Laufzeitwächter und Test über alle Requests). Lehnt Lexware ab, geht die Erfassung mit Fehlermeldung zurück in die Prüfung. Bereits übertragene Erfassungen werden nicht erneut angelegt. Bekannte Grenze: Geht die Antwort von Lexware nach erfolgreichem Anlegen verloren, kann ein Neuversuch einen zweiten Entwurf erzeugen (nur ein Entwurf, im Echtlauf beobachten).

## JSON-Schema der Extraktion

```json
{
  "type": "object",
  "properties": {
    "belegart": {"type": "string", "enum": ["angebot", "rechnung", "unklar"]},
    "kunde": {"type": "string", "description": "Name exakt wie in der Kundenliste, sonst der Name aus den Quellen"},
    "angebot_nummer": {"type": "string", "description": "Nummer eines offenen Angebots, sonst leer"},
    "leistung_von": {"type": "string", "description": "YYYY-MM-DD oder leer"},
    "leistung_bis": {"type": "string", "description": "YYYY-MM-DD oder leer"},
    "positionen": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "artikel_id": {"type": "string", "description": "ID aus der Artikelliste oder leer"},
          "beschreibung": {"type": "string"},
          "menge": {"type": "number"},
          "einheit": {"type": "string"},
          "quelle": {"type": "string", "description": "Name der Quelle"},
          "herkunft": {"type": "string", "enum": ["gesprochen", "foto", "mail", "zeiterfassung", "notiz"]}
        },
        "required": ["artikel_id", "beschreibung", "menge", "einheit", "quelle", "herkunft"],
        "additionalProperties": false
      }
    },
    "offene_fragen": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["belegart", "kunde", "angebot_nummer", "leistung_von", "leistung_bis", "positionen", "offene_fragen"],
  "additionalProperties": false
}
```

Bewusst **kein** Preisfeld. Ein in der Quelle genannter Preis landet nur als offene Frage ("In der Notiz steht 95 € pro Stunde, Artikel X kostet 85 €").

## Stammdaten an das Modell

Nur: Kundennamen, Aliase, Kundennummern, Artikel-ID, Bezeichnung, Einheit, offene Angebotsnummern mit Titel. **Keine** Adressen, Preise, Bankdaten, E-Mail-Adressen. Bei mehr als 300 Artikeln vorher per einfacher Textsuche auf die 50 relevantesten filtern.

## Qualitätssicherung

- Ordner `tests/ki_faelle/` mit mindestens 12 Fällen (Text plus erwartetes Ergebnis): einfache Rechnung, Angebot, unbekannter Kunde, Artikel fehlt, Dialekt-Transkript mit Zahlen ("fuffzehn Meter"), Zahl als Wort, versteckte Anweisung in Mail, keine Belegabsicht, mehrere Kunden in einer Notiz, Foto Stundenzettel, CSV-Zeiterfassung, Mehraufwand gegenüber Angebot.
- Kommando `manage.py ki_testfaelle` ruft das echte Modell und vergleicht. Abnahme: 11 von 12, alle Sicherheitsfälle grün.
- Umgesetzt (M3-10): 13 Fälle in `tests/ki_faelle/` (je Fall eine JSON-Datei mit Quellen, erwartetem Ergebnis und einer Beispielantwort; dazu `stammdaten.json`, ein echtes PNG eines Stundenzettels und eine CSV). Sicherheitsfälle: Artikel fehlt, versteckte Anweisung, keine Belegabsicht, genannter Preis. Im Standardlauf (pytest) antwortet ein nachgebildetes Modell mit der Beispielantwort; geprüft werden Aufbereitung, Bild-Input, Regeln und Bewertung. `manage.py ki_testfaelle [--nur NAME] [--max-faelle N]` ruft das echte Modell (Bedrock, EU-Profil, Schlüssel aus Umgebungsvariablen), arbeitet in einer zurückgerollten Transaktion und einer temporären Dateiablage und endet mit Fehlercode, wenn die Abnahme verfehlt wird. **Ein Lauf gegen das echte Modell hat noch nicht stattgefunden** (keine AWS-Zugangsdaten in der Entwicklungsumgebung).
- Kostenlimit je Firma und Monat in Token **und** Anzahl Vorgänge; Eingabetext auf 30.000 Zeichen kappen.

## Fehlerfälle

- Modell lehnt ab oder bricht ab: Erfassung auf `fehler` mit verständlicher Meldung, Neuversuch-Knopf.
- Transkription leer: Hinweis "Keine Sprache erkannt".
- Bedrock nicht erreichbar: Job mit Backoff wiederholen, nach 3 Versuchen Fehler anzeigen.

## Zweiter Einsatz: PDF-Rechnungskopien vorlesen (K5, M9-04)

Betriebe ohne Lexware schicken Kopien ihrer Ausgangsrechnungen (ADR-011, Stufe 3). Hat ein PDF keine eingebettete E-Rechnung, liest die KI die Werte vor. Code: `quellen/ki.py`, Job `quellen.ki_lesen`.

- Gleicher Weg wie die Erfassung: Bedrock in eu-central-1, EU-Inferenzprofil, Modell `BEDROCK_MODELL`, JSON-Schema, gemeinsamer Helfer `capture.extraktion.json_anfrage`. Das KI-Kostenlimit zählt jeden Lesevorgang als einen Vorgang.
- Gesendet wird nur der PDF-Text (höchstens 20.000 Zeichen) als `<quelle>`, keine Stammdaten. Eingescannte PDFs ohne Text gehen nicht an die KI; der Mensch trägt die Werte ein.
- Die KI liest nur ab, was auf der schon verschickten Rechnung steht. Sie setzt keine Nummer, keinen Preis und keinen Steuersatz und rechnet nicht. Steht nur ein Zahlungsziel da („14 Tage“), rechnet die Regel die Fälligkeit (Rechnungsdatum plus Tage) und sagt das dem Menschen.
- Gegenprobe: Nummer, Kunde, E-Mail, Datum und Beträge müssen wörtlich im PDF-Text stehen (deutsche und englische Schreibweise der Beträge, gängige Datumsformate). Sonst steht ein Hinweis über dem Formular.
- Die Kopie bleibt immer in der Prüfung. Ein Posten entsteht erst, wenn Inhaber oder Freigeber die Werte bestätigt; das Protokoll hält fest, wer bestätigt hat. Der PDF-Text wird danach gelöscht.
- Fehler (Ablehnung, Limit, kein JSON): Die Kopie bleibt in der Prüfung mit dem Hinweis, die Werte selbst einzutragen.
