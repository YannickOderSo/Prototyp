# Prüfliste für das Team (M4-07)

Was vor dem ersten Pilotbetrieb von Menschen geprüft, entschieden oder unterschrieben werden muss. Code allein reicht hier nicht. Jeder Punkt bekommt eine verantwortliche Person, ein Datum und einen Nachweis (Ablageort). Technische Punkte des Echtlaufs stehen im [[Betriebshandbuch]] (Abschnitt 10).

Stand: 5. November 2026. Nichts davon ist erledigt.

## 1. Rechtstexte (F5)

Die App zeigt unter `/rechtliches/<slug>/` derzeit deutlich markierte Platzhalter. `manage.py check --deploy` warnt mit `cockpit.W001`, solange einer davon Platzhalter ist.

- [ ] **Impressum**: Anbieterkennzeichnung nach § 5 DDG.
- [ ] **Datenschutzerklärung**: muss enthalten:
  - Zwecke und Rechtsgrundlagen,
  - Unterauftragsverarbeiter (siehe 2),
  - Speicherdauern laut Löschfristen: Audio sofort, Rohdateien 7 Tage, Erfassungen 12 Monate, Spiegeldaten 30 Tage nach dem Trennen, Protokoll 8 Jahre, Sicherungen bis 12 Monate,
  - Betroffenenrechte,
  - keine Nutzung für KI-Training.
- [ ] **AGB / Nutzungsbedingungen**: müssen regeln:
  - Leistungsbeschreibung: Cockpit, Entwürfe, Freigabe durch den Kunden. Die App erzeugt keine Rechnungen und gibt nichts ohne Freigabe heraus.
  - Haftungsbegrenzung, insbesondere für Mahnungen nach Freigabe durch den Kunden und für Zinsberechnungen.
  - Verfügbarkeit und Kündigung.
  - Export und Löschung bei Vertragsende.
- [ ] **AVV nach Art. 28 DSGVO**: Die Firma ist Verantwortliche, wir sind Auftragsverarbeiter. Inhalt:
  - TOMs (Grundlage: [[Sicherheit-Datenschutz-Betrieb]]),
  - Unterauftragsverarbeiter, Löschfristen, Meldewege bei Datenpannen.
- [ ] Nach Freigabe der Texte: in `web/templates/web/rechtstexte/` einsetzen. In `web/rechtstexte.py` die Version erhöhen und `platzhalter=False` setzen. Neue Versionen erfordern eine erneute Zustimmung (wird je Version gespeichert).

## 2. Verträge mit Dienstleistern (nur EU, ADR-005)

- [ ] Hetzner (Hosting und Storage Box, Deutschland): AVV.
- [ ] Amazon Web Services EMEA (Bedrock, Frankfurt): DPA; schriftlich klären, dass das EU-Inferenzprofil nur in EU-Regionen verarbeitet und keine Daten zum Training genutzt werden.
- [ ] Mistral AI (Transkription, EU): DPA; Verarbeitung in der EU und keine Trainingsnutzung bestätigen.
- [ ] EU-SMTP-Anbieter auswählen (offene Frage), AVV schließen, Entscheidung als ADR festhalten.
- [ ] Mailanbieter für das Belegpostfach (Plus-Adressierung, IMAP, DKIM/SPF-Prüfung): AVV.
- [ ] Fehlererfassung: GlitchTip selbst hosten oder Sentry mit EU-Datenhaltung; ggf. AVV.
- [ ] Lexware: Nutzungsbedingungen der Public API für Partner-Anwendungen lesen. Prüfen, ob eine Registrierung als Partner oder eine Freigabe nötig ist. Jede Firma schließt ihren Vertrag mit Lexware selbst (XL-Tarif erforderlich).
- [ ] Liste der Unterauftragsverarbeiter in App (Datenschutzerklärung) und AVV abgleichen. Entwurf der Liste: [[Datenschutz-Unterlagen]] Abschnitt 1 (7. November 2026).

## 3. Mahnwesen und Zinsen: Prüfung durch Anwalt oder Steuerberater

Grundlage sind [[Mahnlogik-und-Recht]] und die Tabellentests in `tests/dunning/`. Zu prüfen:

- [ ] **Mahntexte** aller Stufen (`dunning/texte.py`): Erinnerung, 1. und 2. Mahnung, Text bei gegenstandsloser Mahnung, Hinweis auf Zinsen und Pauschale, Tonfall.
- [ ] **Verzugsbeginn** (Tabelle in Mahnlogik-und-Recht.md). Zu prüfen sind besonders diese offenen Fragen:
  - Privatkunde mit Verzugshinweis: 30 Tage ab Fälligkeit oder ab Zugang? Umgesetzt: ab dem späteren Datum, Zugang = Belegdatum + 3 Tage.
  - Zeile 4 der Tabelle: Zugang der Stufe 0 plus 1 Tag. Umgesetzt: Versand + 2 (schuldnergünstig). Zeilen 3 und 4 vereinheitlichen.
  - Kann eine frühere Erinnerung den Verzug beim Privatkunden mit Verzugshinweis vor Fälligkeit + 30 auslösen? Umgesetzt: nein.
- [ ] **Zinsen**:
  - Beginn am Folgetag des Verzugsbeginns (§ 187 BGB entsprechend).
  - Zinssatz 5 bzw. 9 Prozentpunkte über dem Basiszins.
  - Abschnittsweise Berechnung bei Wechsel des Basiszinses.
  - Bei Teilzahlungen: Zinsen auf den aktuell offenen Betrag für den ganzen Zeitraum (nie zu viel).
  - Ausweis als nicht umsatzsteuerbare Position (0 %) in der Lexware-Mahnung.
- [ ] **Pauschale** von 40 € nach § 288 Abs. 5 BGB: nur bei Unternehmern, nur einmal je Rechnung, in der 2. Mahnung nicht erneut ausgewiesen. Klären, ob bei Abschlagsrechnungen je Abschlag.
- [ ] **Kundentyp**: Pflicht vor jeder Mahnung, gesetzt durch den Nutzer. Der Lexware-Hinweis Firma/Person wird nie übernommen. Bestätigen, dass Fehlzuordnungen in der Verantwortung des Kunden liegen (AGB).
- [ ] **Steuerberater**: Prüfen, ob Zinsen und Pauschale als Positionen in der Lexware-Mahnung buchhalterisch richtig abgebildet sind. Prüfen, ob Kleinunternehmer und Steuerart „gross“ Sonderfälle brauchen.

## 4. Versicherung und Haftung

- [ ] IT-Haftpflicht bzw. Vermögensschadenhaftpflicht für Software as a Service, Deckung für fehlerhafte Mahnungen und Datenschutzverstöße.
- [ ] Cyber-Versicherung prüfen (Ausfall, Datenpanne).

## 5. Organisation

- [ ] Verantwortliche für Betrieb, Sicherheitsmeldungen und Datenschutzanfragen benennen (Kontakt im Impressum und in der AVV).
- [ ] Verzeichnis von Verarbeitungstätigkeiten als Auftragsverarbeiter (Art. 30 Abs. 2 DSGVO). Entwurf: [[Datenschutz-Unterlagen]] Abschnitt 2, TOMs für die AVV in Abschnitt 3.
- [ ] Ablauf bei Datenpannen (72 Stunden) schriftlich festhalten. Entwurf: [[Datenpannen-Ablauf]]; Namen, Telefonnummern und Aufsichtsbehörde eintragen.
- [ ] Pilotvereinbarung mit dem ersten Betrieb: Umfang, Ansprechpartner, Feedback, Testdaten. Klären, ob mit einem Lexware-Testkonto begonnen wird.
- [ ] Offene Produktfragen aus [[Offene-Fragen]] entscheiden, die „Yannick“ oder „Team“ zugeordnet sind (Produktname und Domain, Validierung Keil A, Altersstruktur, Wochenbericht, technische Löschfristen, Löschung je Firma).
