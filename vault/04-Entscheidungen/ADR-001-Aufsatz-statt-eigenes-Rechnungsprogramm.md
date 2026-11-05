# ADR-001: Aufsatz auf das Bestandstool statt eigenes Rechnungsprogramm

Status: angenommen · 5. November 2026

## Kontext
Lexware Office und sevdesk decken Angebot, Rechnung, E-Rechnung, Archiv und DATEV für 8 bis 35 € im Monat ab. Branchenlösungen (plancraft, HERO, ToolTime) kosten 48 bis 300 € und investieren Millionen in KI. Beiden Marktführern fehlt automatisches Mahnwesen. Lukas' Wettbewerbsanalyse vom 3. November 2026 kam zum selben Schluss.

## Entscheidung
Die App erzeugt keine eigenen Rechnungen, Nummern, E-Rechnungen oder Archive. Sie liest aus dem Bestandstool, legt dort Entwürfe an und versendet nur Zahlungserinnerungen und Mahnungen.

## Folgen
+ Keine GoBD- und E-Rechnungs-Haftung für Rechnungen, kein Systemwechsel beim Kunden, MVP in Wochen.
- Plattformabhängigkeit; Kunde braucht Lexware XL (API). Gegenmittel: zweiter Adapter (sevdesk) in M5.
