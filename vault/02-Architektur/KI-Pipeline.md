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
6. **Regeln** (deterministisch, `capture/rules.py`): Kunde gegen Kontakte des Spiegels (Name, Aliase, Kundennummer); Artikel gegen Artikel des Spiegels; Preis und Steuersatz nur aus Artikel; ohne Artikel Preis leer und Blocker; Mengen > 0; Leistungszeitraum Pflicht bei Rechnungen; Hinweise bei Menge über offenem Angebot.
7. **Prüfansicht:** Positionen mit Herkunft und Hinweisen, editierbar, Blocker verhindern Freigabe.
8. **Übertragung:** `create_invoice_draft` bzw. `create_quotation_draft` im Bestandstool, Link anzeigen, Protokoll.

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
- Kostenlimit je Firma und Monat in Token **und** Anzahl Vorgänge; Eingabetext auf 30.000 Zeichen kappen.

## Fehlerfälle

- Modell lehnt ab oder bricht ab: Erfassung auf `fehler` mit verständlicher Meldung, Neuversuch-Knopf.
- Transkription leer: Hinweis "Keine Sprache erkannt".
- Bedrock nicht erreichbar: Job mit Backoff wiederholen, nach 3 Versuchen Fehler anzeigen.
