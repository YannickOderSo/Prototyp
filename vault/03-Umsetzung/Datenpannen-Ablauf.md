# Ablauf bei Datenpannen (Entwurf)

Stand: 7. November 2026 · **Entwurf, vom Anwalt bzw. von der Datenschutzberatung zu prüfen.** Go-Live-Checkliste „p1-panne“. Platzhalter in eckigen Klammern füllt das Team, danach kann der Punkt abgehakt werden.

## Worum es geht

Eine Datenpanne ist jede Verletzung der Sicherheit, die dazu führt, dass personenbezogene Daten vernichtet, verloren, verändert, unbefugt offengelegt oder unbefugt zugänglich werden (Art. 4 Nr. 12 DSGVO). Beispiele bei Belegfluss: Mahnung an den falschen Empfänger, Zugriff einer Firma auf Daten einer anderen, gestohlene Zugangsdaten, offengelegter Fernet- oder API-Schlüssel, verlorene Sicherung, Einbruch auf dem Server.

**Wer meldet was:**
- Für die Daten der Betriebe (ihre Kunden, Anrufer, Mitarbeiter) ist Belegfluss **Auftragsverarbeiter**. Wir melden dem betroffenen Betrieb die Panne **unverzüglich** (Art. 33 Abs. 2 DSGVO). Die Meldung an die Aufsichtsbehörde binnen 72 Stunden und eine Benachrichtigung der Betroffenen sind Pflicht des Betriebs (Art. 33 Abs. 1, Art. 34); wir unterstützen ihn dabei mit allen Angaben (AVV).
- Für unsere eigenen Daten (Nutzerkonten der Betriebe, Vertragsdaten) sind wir **Verantwortliche** und melden selbst an die Aufsichtsbehörde binnen 72 Stunden ab Kenntnis, wenn ein Risiko für die Betroffenen nicht ausgeschlossen ist.
- Zuständige Aufsichtsbehörde für uns: [Landesdatenschutzbehörde am Sitz des Betreibers, mit Link zum Online-Meldeformular].

## Zuständigkeiten und Kontakte

| Rolle | Person | Erreichbar |
| --- | --- | --- |
| Leitung Vorfall (entscheidet, meldet) | [Name] | [Telefon, auch abends] |
| Vertretung | [Name] | [Telefon] |
| Technik (Eindämmung, Analyse) | [Name] | [Telefon] |
| Anwalt / Datenschutzberatung | [Kanzlei] | [Telefon] |
| Hetzner-Support (Server, Storage Box) | Hetzner Robot | Support-Anfrage im Robot |

Jeder im Team meldet einen Verdacht **sofort** an die Leitung Vorfall, auch außerhalb der Arbeitszeit. Lieber einmal zu viel.

## Ablauf

### 1. Sofort (erste Stunde): erfassen und eindämmen
- Vorfall-Notiz anlegen (Vorlage unten) mit Uhrzeit der Kenntnis. Ab hier läuft die Frist.
- Weiteren Schaden stoppen, je nach Fall:
  - Automatik anhalten: Vorschläge nicht freigeben; im Notfall `docker compose -f docker-compose.prod.yml stop worker` (nichts wird mehr versendet; Freigaben bleiben liegen).
  - Zugänge sperren: betroffene Nutzer deaktivieren, Passwörter und Zwei-Faktor zurücksetzen.
  - Schlüssel tauschen: Fernet-Schlüssel rotieren (Betriebshandbuch Abschnitt 5), `DJANGO_SECRET_KEY` wechseln, ohne den alten Wert in `DJANGO_SECRET_KEY_FALLBACKS` (meldet alle ab), betroffene Lexware-Verbindungen trennen und den Betrieb einen neuen API-Schlüssel erzeugen lassen.
  - Geheime Adressen wechseln: `ZUSTELLUNG_WEBHOOK_TOKEN`, `TELEFON_ASTERISK_TOKEN`, Belegpostfach- und Kopie-Adressen (in der App „Neue Adresse“).
  - Bei Verdacht auf Einbruch: Server vom Netz nehmen (Hetzner-Robot-Firewall alles sperren), nicht neu installieren, bevor Spuren gesichert sind.
- Beweise sichern: Logs (`docker compose logs --since …`), Protokoll in der App (Seite „Berichte“, Export), betroffene Datensätze. Nichts löschen.

### 2. Innerhalb von 24 Stunden: bewerten
- Welche Daten, welche Firmen, wie viele Personen, seit wann? Grundlage: Protokoll (`audit.Protokolleintrag`, 8 Jahre), Versand-Datensätze, Server-Logs.
- Risiko für die Betroffenen einschätzen (z. B. Bankdaten, Zahlungsverhalten, Kontaktdaten). Nicht verschlüsselte Daten und offengelegte Mahnungen gelten als hohes Risiko.
- Ergebnis und Begründung in die Vorfall-Notiz.

### 3. Unverzüglich: betroffene Betriebe informieren
- Jeden betroffenen Betrieb per Telefon und schriftlich (Mail an den Inhaber) informieren, ohne auf die vollständige Analyse zu warten; Ergänzungen folgen.
- Inhalt (Art. 33 Abs. 3 DSGVO): Art der Panne, Kategorien und ungefähre Zahl der Betroffenen und Datensätze, wahrscheinliche Folgen, ergriffene und vorgeschlagene Maßnahmen, Ansprechpartner bei uns.
- Den Betrieb bei seiner Meldung an die Behörde und ggf. an die Betroffenen unterstützen (Texte, Listen der Betroffenen aus `firma_export`).

### 4. Binnen 72 Stunden: eigene Meldung, falls wir Verantwortliche sind
- Betrifft die Panne Nutzerkonten oder Vertragsdaten: Meldung an [Aufsichtsbehörde] über deren Online-Formular, mit denselben Angaben. Ist nach 72 Stunden noch nicht alles bekannt, trotzdem melden und nachreichen; eine Verspätung begründen.
- Bei hohem Risiko auch die betroffenen Nutzer direkt informieren (Art. 34).

### 5. Danach: dokumentieren und verbessern
- Jede Panne wird dokumentiert, auch wenn keine Meldung nötig war (Art. 33 Abs. 5): Vorfall-Notiz vollständig ablegen unter [Ablageort].
- Ursache beheben, Test dafür schreiben, Eintrag in Fortschritt.md und, wenn nötig, ein ADR.
- Nach 30 Tagen kurz prüfen: Wirken die Maßnahmen?

## Vorlage Vorfall-Notiz

```
Vorfall Nr.:            [JJJJ-NN]
Kenntnis am/um:         [Datum, Uhrzeit]   von: [Person/Quelle]
Was ist passiert:       [kurz]
Seit wann (vermutlich): [Datum]
Betroffene Firmen:      [Namen]
Betroffene Personen:    [Kategorien, ungefähre Zahl]
Betroffene Daten:       [Kategorien, ungefähre Zahl der Datensätze]
Risiko:                 [gering / Risiko / hohes Risiko] – Begründung: [ ]
Sofortmaßnahmen:        [was, wann, wer]
Information Betriebe:   [wer, wann, wie]
Meldung Behörde:        [nein, weil … / ja am … durch …, Aktenzeichen …]
Information Betroffene: [nein, weil … / ja am …]
Ursache und Behebung:   [ ]
Abgeschlossen am:       [Datum]   durch: [Person]
```

## Was Belegfluss dafür schon mitbringt

- Protokoll aller Schritte mit Außenwirkung, in der Datenbank gegen Ändern geschützt (zeigt, wer wann was freigegeben oder versendet hat).
- Export je Firma (`manage.py firma_export`) und Löschung je Firma (`manage.py firma_loeschen`).
- Schlüsselrotation ohne Datenverlust (MultiFernet, Betriebshandbuch Abschnitt 5).
- Mandantentrennung mit automatischem Test über alle Seiten.
- Fehlererfassung ohne Inhalte; Überwachung von Erreichbarkeit und Hintergrunddiensten.
