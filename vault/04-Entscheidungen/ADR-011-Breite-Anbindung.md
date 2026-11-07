# ADR-011: Breite Anbindung an Rechnungsprogramme in drei Stufen

Status: **angenommen** · 6. November 2026 (Yannick: „Dann fang an zu bauen“, zuerst Stufe 3) · ergänzt ADR-001, ADR-003, ADR-005 und ADR-008

## Kontext
Eine Pilotkundin „nutzt DATEV“. Belegfluss soll möglichst viele Betriebe erreichen, unabhängig vom Rechnungsprogramm. Bisher gibt es nur Lexware Office (ADR-003). `Vision-und-Abgrenzung.md` schließt eine DATEV-Anbindung aus. Recherche vom 6. November 2026 (Quellen in [[Anbindungen-Recherche]]):
- „Nutzt DATEV“ heißt bei kleinen Betrieben meist: Der **Steuerberater** nutzt DATEV, die Rechnungen entstehen in einem anderen Programm.
- Wer selbst in **DATEV Auftragswesen next** schreibt, hat keine API zum Lesen von Rechnungen, offenen Posten oder Zahlstatus und keine zum Anlegen von Entwürfen. Die DATEV-Online-APIs gehen fast nur in Richtung DATEV (Belege und Buchungen hochladen); das Onboarding kostet 1.500 € und dauert Wochen. Offene Posten sind nur über DATEVconnect im Netz der Kanzlei lesbar.
- Gute APIs mit Entwürfen ohne Nummer: Lexware Office, sevdesk (ohne Webhooks), easybill, Billomat, orgaMAX/MeinBüro (Buhl), Papierkram, FastBill. Viele Handwerkerprogramme (HERO, ToolTime, Das Programm, Meisterwerk) geben ihre Rechnungen an Lexware Office oder sevdesk weiter.
- Sammel-APIs (Unified APIs): Die EU-tauglichen (Chift, Maesn) decken bei Rechnungsprogrammen nur Lexware Office, sevdesk und DATEV ab; US-Anbieter scheiden aus (ADR-005).

## Vorschlag
1. **Stufe 1, für jedes Programm (vorhanden):** Offene Posten per Excel/CSV-Import (ADR-008), Mahnwesen mit Mahnschreiben-PDF der App, Zahlstatus von Hand. Neu: Der Entwurf aus dem Sprachmemo wird bei Programmen ohne API als Positionsliste zum Übertragen ausgegeben, deutlich als Entwurf markiert, ohne Nummer und ohne Rechnungscharakter (ADR-001 bleibt).
2. **Stufe 2, direkte Adapter** gegen `AccountingConnector`, in dieser Reihenfolge nach Nachfrage der Pilotbetriebe: sevdesk (M5), easybill, orgaMAX/MeinBüro, Billomat. Jeder Adapter muss die harten Regeln einhalten: nur Entwürfe, nie Nummern, nie finalisieren, Test über alle Anfragen.
3. **Stufe 3, automatisch ohne Programm-API (später):** Kopie der ausgehenden E-Rechnung (ZUGFeRD/XRechnung) ins Belegpostfach als Quelle für offene Posten, Zahlungseingänge über eine Kontoanbindung nach PSD2 mit Anbieter in der EU (z. B. finAPI, BaFin-registriert). Grenzen: Rechnungen an Privatkunden sind nicht E-Rechnungs-pflichtig, bis 2027/2028 verschicken viele noch PDFs.
4. **Keine eigene DATEV-Anbindung** und keine Sammel-API, solange kein Pilotbetrieb sie zwingend braucht. DATEV-Fälle laufen über Stufe 1 bzw. 3.

## Folgen
+ Jeder Betrieb kann ab dem ersten Tag starten (Stufe 1); die Automatik wächst mit jedem Adapter.
+ Volle Kontrolle über die Entwurfs-Regeln, keine zusätzlichen Auftragsverarbeiter außerhalb der EU.
- Stufe 1 bedeutet Handarbeit beim Zahlstatus; Stufe 3 kostet eine PSD2-Anbindung (finAPI ab ca. 300 €/Monat laut Preisliste) und einen E-Rechnungs-Parser.

## Umsetzung Stufe 3 (M9, 6. November 2026)
- Posten aus Rechnungskopien bekommen die Quelle „Rechnungskopie“ und laufen wie importierte Posten (ADR-008): nie in einem Bestandstool gebucht, Zahlstatus in Belegfluss, Mahnschreiben-PDF der App, Erinnerung ohne Anhang.
- Für Betriebe ohne Lexware legt Belegfluss Kunden im Cockpit an (Name, E-Mail, Anschrift aus der E-Rechnung). Das erweitert ADR-008 Punkt 1 und H6 nur für diesen Weg. Seit M9-08 kann auch der Excel-Import ohne Lexware Kunden und offene Rechnungen anlegen (ADR-008 Nachtrag).
- Zahlungen aus Kontoauszügen ändern den Zahlstatus erst nach Bestätigung durch einen Menschen. Gespeichert werden nur Gutschriften, keine Abbuchungen.
- Die Kopie-Dateien selbst werden nicht aufbewahrt, nur die gelesenen Felder (Archiv bleibt beim Bestandstool, ADR-001).
- Stand 6. November 2026: A (E-Rechnungs-Kopien), A2 (PDF per KI, Mensch bestätigt) und B1 (Kontoauszug camt.053/camt.052/CSV) sind gebaut (M9-02 bis M9-07). B2 (Kontoabruf über finAPI) folgt erst nach einem Vertrag mit finAPI.
- Posten aus Kopien sind keine Spiegeldaten: Sie bleiben beim Trennen von Lexware erhalten. Ihre Kunden ebenfalls, auch wenn sie aus Lexware stammen.
- Eine noch nicht zugeordnete Zahlung, die zu einem Posten passt, sperrt den Versand der Mahnung zu diesem Posten (zusätzlicher Frische-Check).
- Grenzen: Artikel aus Excel nur mit Lexware.

## Umsetzung Stufe 1: Positionsliste zum Abtippen (M9-09, 7. November 2026)
- Ohne Lexware (keine oder nur getrennte Verbindung) endet die Belegerfassung nicht mit einem Entwurf in Lexware, sondern mit einer **Positionsliste**: Kunde, Leistungszeitraum, Angebotsbezug und Positionen (Beschreibung, Menge, Einheit; Preis und Steuersatz nur, wenn ein Mensch sie gesetzt hat).
- Die Liste ist deutlich als „Entwurf – keine Rechnung“ markiert, hat keine Nummer und keinen Empfänger-Briefkopf und wird nicht versendet. Ansicht zum Drucken und CSV (Semikolon, deutsche Zahlen, gegen Formeln geschützt) zum Übertragen ins eigene Programm.
- Freigeben wie bisher nur Inhaber und Freigeber; Status „als Positionsliste ausgegeben“, Protokoll für Ausgabe und CSV-Download.
- Ohne Lexware sind ein Kunde, der nicht im Kundenstamm steht, und fehlende Preise **Hinweise statt Blocker**. Fehlende Menge, fehlende Belegart, fehlender Leistungszeitraum bei Rechnungen und ein ganz fehlender Kunde bleiben Blocker. Mit Lexware ändert sich nichts.
