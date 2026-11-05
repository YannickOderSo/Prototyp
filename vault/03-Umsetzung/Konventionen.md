# Konventionen

- **Sprache:** Fachbegriffe im Code deutsch, wo sie Domäne sind (`Mahnvorschlag`, `verzugsbeginn`), sonst englisch für Technik (`connector`, `job`). Oberfläche komplett deutsch, Sie-Form gegenüber Kunden der Betriebe, Du oder Sie in der App einheitlich Sie.
- **Geld:** immer `Decimal`, Rundung kaufmännisch (`ROUND_HALF_UP`) auf Cent, nie `float`.
- **Zeit:** UTC in der DB, `Europe/Berlin` in Anzeige und Fristen; Fristberechnung mit Datumswerten, nicht Zeitstempeln.
- **Struktur:** fachliche Logik in `services.py` bzw. reinen Modulen, Views dünn. Keine Logik in Templates.
- **Fehler:** nach außen verständliche deutsche Meldung, nach innen strukturierter Log mit IDs, ohne personenbezogene Inhalte.
- **Commits:** klein, Ticket-ID im Titel (`M2-03: Vorschlagslauf idempotent`).
- **Vault pflegen:** Wer eine Entscheidung ändert, schreibt ein neues ADR. Wer eine offene Frage findet, trägt sie in `05-Kontext/Offene-Fragen.md` ein.
- **Verboten:** `finalize=true` an Bestandstools, Versand ohne Freigabe, Preise oder Steuersätze aus KI-Ausgaben, US-Endpunkte für personenbezogene Daten, Geheimnisse im Repo.
- **Oberfläche (Design-System, seit 5. November 2026):**
  - Alles steht in `web/static/web/style.css`: Farben, Abstände und Radien als CSS-Variablen in `:root`. Neue Seiten nutzen die vorhandenen Bausteine `karte`, `liste`, `zeile`, `neben`, `kennzahl`, `marke-status`, `meldung`, `knopf`, `knopfreihe`, `raster zwei` und `aktionsleiste`, keine eigenen Farben.
  - Farbe nur für Status (gut, warnung, schlecht) und die Hauptaktion. Beträge in Ziffern fester Breite und rechtsbündig.
  - Desktop ab 1024 px mit Seitenleiste. Auf dem Handy höchstens vier Hauptziele in der unteren Leiste, der Rest unter „Mehr“. Neue Navigationspunkte kommen in `web/context.py` (mit Icon aus `web/icons.py`).
  - Keine Inline-Styles und keine externen Schriften oder Icons (CSP, Datenschutz). Lizenzen in `THIRD_PARTY.md`.
