# Teststrategie

- **pytest** mit `pytest-django`, echte Postgres-Datenbank in CI.
- **Reine Logik** (Verzug, Zinsen, Pauschale, Altersstruktur, Prognose, Regeln der Erfassung): Tabellen-Tests, je Rechtsregel mindestens ein Test, Grenzfälle (Schaltjahr, Basiszinswechsel, Teilzahlung, Fälligkeit fehlt).
- **Connectoren:** aufgezeichnete HTTP-Antworten (`pytest-recording`/VCR) aus dem Lexware-Testkonto; Schlüssel werden beim Aufzeichnen geschwärzt. Ein Test stellt sicher, dass kein Request `finalize=true` enthält.
- **Mandantentrennung:** generischer Test über alle URL-Muster mit IDs.
- **Mail:** lokal und in CI gegen Mailpit; Inhalt, Anhang und Header (Reply-To) prüfen. Umgesetzt: Tests mit Marker `mailpit` laufen, wenn `MAILPIT_URL` gesetzt ist (CI-Service `axllent/mailpit`, lokal `docker compose up mailpit`); sonst werden sie übersprungen. Alle anderen Mail-Tests nutzen das locmem-Backend.
- **KI:** im Standardlauf gemockt; echte Fälle nur über `manage.py ki_testfaelle` mit eigenem Kostenlimit.
- **Ende-zu-Ende:** Playwright für die drei Hauptwege (Verbinden, Freigeben, Erfassen) auf Handy-Viewport 390 × 844.
  Umgesetzt (`tests/e2e/test_hauptablaeufe.py`, CI-Job „Playwright“):
  - Jeder Ablauf meldet sich über die Oberfläche mit Passwort und TOTP-Code an und prüft auf jeder Seite, dass es keine horizontale Scrollleiste gibt.
  - Lexware verbinden: Einrichtung → Schlüssel → Erstimport → Postenliste.
  - Mahnungen freigeben: Freigeber gibt frei → Versand mit Frische-Check → Mail mit PDF.
  - Sprachmemo zu Entwurf: Aufnahme mit dem Fake-Mikrofon von Chromium → Transkript prüfen → Entwurf prüfen → Freigabe → Rechnungsentwurf in Lexware, Preis aus dem Artikel, ohne finalize.
  - Lexware, Mistral und KI sind nachgebaut. Jobs führt der Test aus, weil kein Worker-Prozess läuft.
- **Abdeckung:** `dunning` und `capture/rules` mindestens 90 % Zeilen, Rest ohne Vorgabe.
- **Echtlauf-Checkliste** vor jedem Pilotkunden: Lexware-Testkonto verbinden, Abgleich prüfen, eine Erinnerung und eine Mahnung an eine eigene Adresse senden, ein Sprachmemo zu einem Entwurf machen, Restore-Probe.
