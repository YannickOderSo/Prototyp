# Arbeitsanweisung für Agenten

Dieses Repository baut das **Forderungs- und Abrechnungs-Cockpit** (Arbeitstitel). Die vollständige Spezifikation liegt im Ordner `vault/` (Obsidian-kompatibel, reines Markdown).

Lies vor jeder Arbeit in dieser Reihenfolge:

1. `vault/00-Start-hier.md`
2. `vault/04-Entscheidungen/` (alle ADRs, sie sind bindend)
3. `vault/03-Umsetzung/Meilensteine-und-Tickets.md` und arbeite das nächste offene Ticket ab

Harte Regeln, die nie gebrochen werden:

- Die KI erzeugt nur **Entwürfe**. Nichts verlässt die App ohne menschliche Freigabe.
- Die KI setzt **nie** Preise, Steuersätze oder Rechnungsnummern. Das machen Regeln und das Bestandstool.
- Rechnungen, Nummern, E-Rechnung und Archiv bleiben im **Bestandstool** (Lexware Office, später sevdesk). Diese App baut kein eigenes Rechnungsprogramm.
- Personenbezogene Daten werden nur in der **EU** verarbeitet.
- Jeder Schritt mit Außenwirkung wird im Protokoll festgehalten.
- Von Grund auf selbst bauen. Code aus `belegfluss` (Lukas) nur als Orientierung; Übernahme nur nach den Bedingungen in ADR-007, mit Herkunftsvermerk und eigenen Tests.

Wenn eine Spezifikation fehlt oder widersprüchlich ist: in `vault/05-Kontext/Offene-Fragen.md` eintragen, die konservativste Annahme treffen und weiterarbeiten.
