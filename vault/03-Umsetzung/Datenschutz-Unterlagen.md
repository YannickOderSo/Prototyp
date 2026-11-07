# Datenschutz-Unterlagen (Entwurf)

Stand: 7. November 2026 · **Entwurf als Grundlage für Anwalt bzw. Datenschutzberatung, keine Rechtsberatung.** Platzhalter in eckigen Klammern füllt das Team. Quelle für alle technischen Angaben: [[Sicherheit-Datenschutz-Betrieb]], [[Datenmodell]], [[Betriebshandbuch]] und der Code (Löschfristen in `audit/loeschfristen.py`).

Deckt die Punkte der Go-Live-Checkliste ab:
- **p1-uav** Liste der Unterauftragsverarbeiter (Abschnitt 1), abgleichen mit Datenschutzerklärung und AVV,
- **p1-vvt** Verzeichnis der Verarbeitungstätigkeiten nach Art. 30 DSGVO (Abschnitt 2),
- Anlage „TOMs“ für die AVV (Abschnitt 3, Teil von **p1-rechtstexte**).
Der Ablauf bei Datenpannen (**p1-panne**) steht in [[Datenpannen-Ablauf]].

## Rollen

- **Betrieb (Kunde von Belegfluss):** Verantwortlicher für die Daten seiner Kunden, Anrufer und Mitarbeiter.
- **[Betreiber von Belegfluss, Rechtsform, Anschrift]:** Auftragsverarbeiter für diese Daten (AVV nach Art. 28 DSGVO mit jedem Betrieb). Verantwortlicher nur für die eigenen Vertrags- und Kontodaten der Betriebe (Abschnitt 2, Teil A).
- **Lexware** ist kein Unterauftragsverarbeiter von Belegfluss: Der Betrieb hat einen eigenen Vertrag mit Lexware; Belegfluss greift in seinem Auftrag über die Schnittstelle zu.

## 1. Unterauftragsverarbeiter

Regel (ADR-005): Personenbezogene Daten nur in der EU, keine Ausweichendpunkte außerhalb. Status „offen“ heißt: Vertrag bzw. AVV noch nicht geschlossen.

| Anbieter | Zweck | Daten | Ort | Status |
| --- | --- | --- | --- | --- |
| Hetzner Online GmbH | Server (AX41, Falkenstein), Sicherungen (Storage Box, anderer Standort) | alle Daten von Belegfluss (verschlüsselte Sicherungen) | Deutschland | offen (p2-hetzner) |
| Amazon Web Services EMEA SARL | KI über Amazon Bedrock: Belegerfassung, PDF-Rechnungskopien vorlesen, Gesprächsführung am Telefon | Transkripte, Notizen, Mailtexte, Fotos, PDF-Text, Gesprächsbeiträge, Kunden- und Artikelnamen (gefiltert) | Region eu-central-1 (Frankfurt), EU-Inferenzprofil (nur EU-Regionen, schriftlich bestätigen lassen) | offen (p2-aws) |
| Mistral AI SAS | Spracherkennung (Sprachmemos, Telefon) und Sprachausgabe am Telefon (Voxtral) | Audio (nicht gespeichert), Text der Ansagen | EU (bestätigen lassen) | offen (p2-mistral) |
| Mailjet SAS (Vorschlag, ADR-012) | Versand von Erinnerungen, Mahnungen, Angebots-Erinnerungen, Sammel- und Systemmails; Zustellmeldungen | Empfänger-Adresse, Betreff, Text, PDF-Anhang | EU (Datenstandort und eigene Unterauftragsverarbeiter vor Vertrag prüfen) | offen (p0-mail, p2-mailjet) |
| Heinlein Hosting GmbH (mailbox.org) | Sammelpostfach für Belegpostfach und Rechnungskopien (IMAP) | eingehende Mails mit Anhängen bis zum Abruf | Deutschland | offen (p2-mailbox) |
| easybell GmbH | SIP-Trunk und Rufnummern für den Telefonassistenten | Rufnummer des Anrufers, gewählte Nummer, Sprachdaten während des Gesprächs | Deutschland | offen, erst mit Telefon (p5-easybell, p5-uav) |
| Fehlererfassung: GlitchTip (gehostet) oder selbst gehostet | technische Fehlermeldungen | Fehlertext, Stacktrace ohne lokale Variablen, Nutzer-ID; keine Anfrage-Inhalte (`cockpit/fehlererfassung.py`) | **prüfen:** Sitz und Standort des gehosteten Dienstes; liegt er nicht in der EU, GlitchTip auf dem eigenen Server betreiben | offen (p2-glitchtip) |
| finAPI GmbH (später, Stufe B2) | Kontoabruf nach PSD2 statt Hochladen von Kontoauszügen | Kontoumsätze (Belegfluss speichert nur Gutschriften) | Deutschland | nicht vorgesehen vor einem Vertrag |

Keine Unterauftragsverarbeiter, weil sie keine Kundendaten verarbeiten: Uptime-Überwachung (ruft nur `/healthz` ohne Inhalte auf), GitHub (Code und erfundene Demo-Daten; CI ohne echte Daten), Domain-Registrar.

**Abgleich:** Diese Liste ersetzt die kurze Aufzählung in [[Sicherheit-Datenschutz-Betrieb]] (dort noch ohne mailbox.org, easybell und Fehlererfassung). Datenschutzerklärung und AVV-Anlage aus dieser Tabelle befüllen.

## 2. Verzeichnis der Verarbeitungstätigkeiten (Art. 30 DSGVO)

Allgemein für alle Einträge: keine Übermittlung in Drittländer; technische und organisatorische Maßnahmen siehe Abschnitt 3; Sicherungen werden 30 Tage täglich und 12 Monate monatlich aufbewahrt (gelöschte Daten verschwinden aus den Sicherungen erst nach deren Ablauf).

Angaben zum Betreiber: [Name, Anschrift, Vertretungsberechtigte, Kontakt für Datenschutz]. Datenschutzbeauftragter: [prüfen, ob nach § 38 BDSG nötig; bei kleinem Team in der Regel nicht].

### Teil A: Belegfluss als Verantwortlicher (Art. 30 Abs. 1)

| Verarbeitung | Zweck und Rechtsgrundlage | Betroffene und Daten | Empfänger | Löschung |
| --- | --- | --- | --- | --- |
| Nutzerkonten der Betriebe | Bereitstellung des Dienstes, Vertrag (Art. 6 Abs. 1 lit. b) | Inhaber, Freigeber, Mitarbeiter: Name, E-Mail, Passwort-Hash, Zwei-Faktor-Geheimnis (verschlüsselt), Rolle, Zustimmungen zu Rechtstexten | Hetzner | mit der Löschung der Firma; Nutzer im Protokoll bleiben deaktiviert bis zu dessen Frist |
| Vertragsabwicklung und Abrechnung | Vertrag, gesetzliche Aufbewahrung (lit. b, c) | Ansprechpartner der Betriebe: Name, Anschrift, Rechnungsdaten | [eigene Buchhaltung, Steuerberatung] | nach den gesetzlichen Fristen (HGB, AO) |
| Sicherheitsprotokoll | Nachweis gegenüber den Betrieben, Sicherheit (lit. c, f) | Nutzer: Aktionen mit Zeitpunkt (z. B. Freigaben) | Hetzner | 8 Jahre |
| Support-Anfragen | Vertrag (lit. b) | Anfragende: Name, E-Mail, Inhalt | [Support-Postfach-Anbieter] | [Frist festlegen, Vorschlag 12 Monate nach Abschluss] |

### Teil B: Belegfluss als Auftragsverarbeiter (Art. 30 Abs. 2)

Verantwortliche: die einzelnen Betriebe (Liste der Kunden mit Kontakt, je AVV). Kategorien der Verarbeitungen im Auftrag:

| Verarbeitung | Betroffene | Daten | Unterauftragsverarbeiter | Löschung |
| --- | --- | --- | --- | --- |
| Cockpit offener Posten (Spiegel aus Lexware) | Kunden des Betriebs, Ansprechpartner | Name, E-Mail, Kundennummer, Firma/Person, Rechnungsadresse; Kopfdaten von Rechnungen und Angeboten (Nummer, Datum, Fälligkeit, Betrag, offener Betrag, Status) | Hetzner | 30 Tage nach dem Trennen von Lexware |
| Erinnerungen und Mahnungen | Kunden des Betriebs | zusätzlich Mahnstufe, Zinsen, Pauschale, Mailtext, Empfänger, Zustellstatus; Mahnschreiben-PDF nur bei Postversand | Hetzner, Mailjet | mit dem zugehörigen Beleg; Protokoll 8 Jahre |
| Angebots-Erinnerungen | Kunden des Betriebs | Angebot (Nummer, Betrag, Gültigkeit), Mailtext, Empfänger | Hetzner, Mailjet | mit dem zugehörigen Angebot |
| Belegerfassung (Sprachmemo, Foto, Mail, Zeiterfassung) | Inhaber des Betriebs (Stimme), Kunden des Betriebs | Audio (sofort nach der Transkription gelöscht), Transkript, Fotos und Dateien, Mailtexte, KI-Ergebnis, Entwurf | Hetzner, Mistral, AWS, mailbox.org (Belegpostfach) | Rohdateien 7 Tage, Erfassung 12 Monate |
| KI-Telefonassistent | Anrufer, Kunden des Betriebs | Rufnummer, Name, Anliegen, Rückrufnummer, Dringlichkeit, Gesprächsverlauf als Text (kein Audio gespeichert) | Hetzner, easybell, Mistral, AWS, Mailjet (Hinweis-Mail ans Team nur mit Name, Dringlichkeit und Link) | Verlauf 90 Tage; Rückruf-Notiz 90 Tage nach „erledigt“, höchstens 12 Monate |
| Rechnungskopien (ohne Lexware) | Kunden des Betriebs | gelesene Felder der Rechnung (Nummer, Daten, Kunde, Anschrift, E-Mail, Beträge); keine Dateien; PDF-Text nur bis zum Vorlesen durch die KI | Hetzner, mailbox.org (Kopie-Adresse), AWS (nur PDF ohne E-Rechnung) | 12 Monate; PDF-Text spätestens nach 7 Tagen |
| Kontoauszüge (ohne Lexware) | Zahler (Kunden des Betriebs) | nur Gutschriften: Datum, Betrag, Name des Zahlers, gekürzte IBAN, Verwendungszweck; keine Dateien, keine Abbuchungen | Hetzner | 12 Monate |
| Import aus Excel | Kunden des Betriebs | gelesene Zeilen (Kunden, Artikel, offene Rechnungen) bis zur Freigabe | Hetzner | Zeilen nach 7 Tagen; angelegte Kunden und Posten wie oben |
| Technische Reste | wie oben | Jobs, Webhook-Ereignisse, Postfach-Eingänge, Sammelmail-Nachweise | Hetzner | Jobs 30 bzw. 90 Tage, Webhook-Ereignisse 90 Tage, Postfach-Eingänge und Sammelmails 12 Monate |

## 3. Technische und organisatorische Maßnahmen (Anlage zur AVV, Kurzfassung)

| Bereich | Maßnahmen |
| --- | --- |
| Zutritt | Rechenzentrum von Hetzner in Deutschland (laut Hetzner nach ISO/IEC 27001 zertifiziert; Zertifikat für die Anlage anfordern). Kein eigener physischer Zutritt nötig. |
| Zugang | SSH nur mit Schlüssel, kein Passwort- und kein Root-Login; Firewall (Hetzner Robot und `ufw`) nur mit den nötigen Ports; Zwei-Faktor-Anmeldung für alle Dienstkonten; Geheimnisse im Passwort-Manager. |
| Zugriff in der App | Anmeldung mit Zwei-Faktor; Rollen Inhaber, Freigeber, Mitarbeiter; Freigaben mit Außenwirkung nur Inhaber oder Freigeber; Ratenlimits gegen Passwortraten. |
| Trennung der Mandanten | Jede fachliche Tabelle mit Firmenbezug, Abfragen nur über einen Manager je Firma; automatischer Test über alle Seiten mit IDs (fremde Daten ergeben 404). |
| Weitergabe | TLS für alle Verbindungen (HSTS), Mails per STARTTLS; nur EU-Endpunkte, ein Systemcheck verhindert den Start mit Nicht-EU-Endpunkten für KI und Fehlererfassung. |
| Verschlüsselung | API-Schlüssel, SMTP-Passwörter und Zwei-Faktor-Geheimnisse verschlüsselt (Fernet mit Schlüsselrotation); Sicherungen verschlüsselt (restic). |
| Eingabekontrolle | Protokoll jedes Schritts mit Außenwirkung (wer, wann, was), in der Datenbank gegen Ändern und Löschen geschützt, 8 Jahre. |
| Verfügbarkeit | RAID 1, tägliche verschlüsselte Sicherung an einem zweiten Standort, monatliche Restore-Probe, Überwachung von Erreichbarkeit und Hintergrunddiensten, automatische Sicherheitsupdates. |
| Datenminimierung | Die KI bekommt nur, was sie braucht (gefilterte Stammdaten, PDF-Text statt Datei); Audio wird nach der Transkription gelöscht; Dateien aus Rechnungskopien und Kontoauszügen werden nicht gespeichert; IBANs nur gekürzt; keine Nutzung für KI-Training (vertraglich bestätigen lassen). |
| Löschung | Täglicher Löschlauf nach festen Fristen (Abschnitt 2); Export und Löschung je Firma auf Verlangen (`firma_export`, `firma_loeschen`). |
| Auftragskontrolle | AVV mit jedem Unterauftragsverarbeiter (Abschnitt 1), nur Anbieter in der EU. |
| Vorfälle | [[Datenpannen-Ablauf]]: Meldung an den Betrieb unverzüglich. |
