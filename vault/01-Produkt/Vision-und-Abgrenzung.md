# Vision und Abgrenzung

## Ein Satz

**Damit kleine Betriebe ihr Geld schneller bekommen, ohne ihr Rechnungsprogramm zu wechseln.**

## Positionierung

- Zielgruppe: Handwerksbetriebe und kleine Dienstleister, 3 bis 20 Mitarbeiter, Inhaber oder eine Bürokraft machen die Rechnungen, nutzen **Lexware Office** (Tarif XL wegen API) oder sevdesk.
- Versprechen: "Montags 5 Minuten freigeben, den Rest erledigt das Cockpit."
- Messgröße für Kundennutzen: durchschnittliche Tage von Fälligkeit bis Zahlungseingang (sinkt) und Summe überfälliger Forderungen (sinkt).
- Preisrahmen laut Konzept: 49 bis 99 € pro Monat, Einrichtung 199 bis 490 €.

## Im Produkt

- Forderungs-Cockpit, Mahnautomatik mit Freigabe, Erfassung per Sprache/Foto/Mail zu Entwürfen im Bestandstool, wöchentlicher Bericht, Protokoll.

## Bewusst nicht im Produkt (bis auf Widerruf per ADR)

- Kein eigenes Rechnungsprogramm: keine eigenen Rechnungsnummern, keine eigene E-Rechnungs-Erzeugung, kein eigenes GoBD-Archiv.
- Kein autonomer Versand ohne Freigabe.
- Kein eigener Bankabruf mit PSD2-Lizenz. Zahlstatus kommt aus dem Bestandstool.
- Kein CRM, keine Plantafel, keine Zeiterfassung, kein Lager, kein Aufmaß.
- Keine native App. Mobile Web-App (responsive, PWA-fähig) reicht.
- Keine DATEV-Anbindung. Das Bestandstool liefert DATEV.

## Spätere Option (nicht bauen, aber Architektur nicht verbauen)

- **Keil B: Bau-Abrechnung** für Subunternehmer (kumulierte Abschläge, Sicherheitseinbehalt, § 13b, Bauabzugsteuer als E-Rechnung). Würde ein eigenes Belegmodul erfordern. Siehe `05-Kontext/Konzept-Zusammenfassung.md`.
