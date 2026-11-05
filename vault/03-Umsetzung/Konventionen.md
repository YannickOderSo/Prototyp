# Konventionen

- **Sprache:** Fachbegriffe im Code deutsch, wo sie Domäne sind (`Mahnvorschlag`, `verzugsbeginn`), sonst englisch für Technik (`connector`, `job`). Oberfläche komplett deutsch, Sie-Form gegenüber Kunden der Betriebe, Du oder Sie in der App einheitlich Sie.
- **Geld:** immer `Decimal`, Rundung kaufmännisch (`ROUND_HALF_UP`) auf Cent, nie `float`.
- **Zeit:** UTC in der DB, `Europe/Berlin` in Anzeige und Fristen; Fristberechnung mit Datumswerten, nicht Zeitstempeln.
- **Struktur:** fachliche Logik in `services.py` bzw. reinen Modulen, Views dünn. Keine Logik in Templates.
- **Fehler:** nach außen verständliche deutsche Meldung, nach innen strukturierter Log mit IDs, ohne personenbezogene Inhalte.
- **Commits:** klein, Ticket-ID im Titel (`M2-03: Vorschlagslauf idempotent`).
- **Vault pflegen:** Wer eine Entscheidung ändert, schreibt ein neues ADR. Wer eine offene Frage findet, trägt sie in `05-Kontext/Offene-Fragen.md` ein.
- **Verboten:** `finalize=true` an Bestandstools, Versand ohne Freigabe, Preise oder Steuersätze aus KI-Ausgaben, US-Endpunkte für personenbezogene Daten, Geheimnisse im Repo.
