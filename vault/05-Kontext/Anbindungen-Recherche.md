# Recherche: Anbindung weiterer Rechnungsprogramme

Stand 6. November 2026. Kurzfassung der Recherche zu ADR-011; Herstellerangaben, nicht unabhängig geprüft.

## DATEV
- Rechnungsprogramme für Betriebe: DATEV Auftragswesen next (online, 7 €/Monat, Modul von Unternehmen online), DATEV E-Rechnungsschreibung (sehr klein), DATEV Mittelstand Faktura (wird zum 31.12.2026 eingestellt). Belege online, Kassenbuch online und Bank online schreiben keine Rechnungen.
- Online-APIs („Datenservices“): Rechnungsdatenservice, Buchungsdatenservice, Belegtransfer, alle in Richtung DATEV. Keine API gefunden, um Ausgangsrechnungen, offene Posten oder Zahlstatus zu lesen oder Entwürfe in Auftragswesen next anzulegen. Anmeldung per DATEV-Login (OpenID Connect) mit Freigabe durch die Kanzlei.
- Onboarding: Pflicht-Beratungspaket 1.500 € zzgl. USt, Sandbox- und Produktionsprüfung, mehrere Wochen. Marktplatz-Partner erst ab 25 Kunden und 3 Referenzen.
- DATEVconnect (Desktop, im Netz der Kanzlei) kann offene Posten lesen (Beispiel: Debitorcloud), braucht aber die Kanzlei und geht nicht bei DATEV-gehosteten Kanzleien.
- Ohne API: OPOS-Liste der Kanzlei als CSV/Excel; DATEV-Format (EXTF) taugt als Rechnungsliste, nicht für den Zahlstatus.
- Quellen u. a.: datev.de (Produkt- und Shopseiten Auftragswesen next, Datenservices, DATEVconnect, Marktplatz Debitorcloud), terminland.de/datev_schnittstellenberatung (Onboarding), DATEV-Community (Auftragswesen next API).

## Andere Programme (öffentliche API, Entwürfe ohne Nummer, Webhooks)
| Programm | API | Entwürfe | Webhooks | Tarif für API | Verbreitung (Hersteller) |
|---|---|---|---|---|---|
| Lexware Office | REST | ja | ja, auch Zahlungen | XL | Lexware gesamt 650.000+ |
| sevdesk | REST | Rechnungen ja, Angebote mit Nummernpflicht (offen) | nein | Buchhaltung Pro | 170.000+ |
| easybill | REST | ja | ja, auch Zahlungen | ab Professional | 80.000+ |
| Billomat | REST | ja, Nummer erst beim Abschließen | ja, auch Zahlungen | ab Business | – |
| orgaMAX / MeinBüro (Buhl) | REST (OpenAPI) | ja, Nummer erst beim Abschließen | nein | – | orgaMAX 60.000 |
| Papierkram | REST (Beta) | ja | nein | Paket M/L | – |
| FastBill | XML/JSON | ja | ja, ohne Zahlungen | nach Tarif | 70.000+ |
| Das Programm (Handwerk) | GraphQL (Pro) | nur Angebote | – | Pro | 12.000+ |
| HERO (Handwerk) | GraphQL | keine Dokumente | – | ab HERO OS | gibt an Lexware Office weiter |
Ohne nutzbare API: plancraft, Taifun, Streit V.1, Zervant, Craftnote (keine Rechnungen), ToolTime (Beta). invoiz wird zum 30.11.2026 abgeschaltet.

## Sammel-APIs und universelle Wege
- Chift (Brüssel, EU-Hosting) und Maesn (Deutschland): Lexware Office, sevdesk, DATEV; keine Handwerkersoftware, kein easybill/Billomat/Buhl. Apideck, Merge, Codat, Rutter, unified.to: US-Bezug oder keine deutschen Programme.
- E-Rechnung: Empfangspflicht seit 2025, Ausstellung ab 2027 (über 800.000 € Umsatz) bzw. 2028; B2C und Kleinbeträge ausgenommen. Enthält Nummer, Käufer, Betrag, Fälligkeit, aber keinen Zahlstatus.
- Kontoanbindung (PSD2): finAPI (München, BaFin), öffentliche Preise ab ca. 300 €/Monat inkl. Lizenzanteil; GoCardless nimmt keine Neukunden; Tink (Visa-Gruppe) nur auf Anfrage.
