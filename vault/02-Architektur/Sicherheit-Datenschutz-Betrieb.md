# Sicherheit, Datenschutz, Betrieb

## Sicherheit

- Django-Standardschutz: CSRF, Autoescaping, Secure/HttpOnly-Cookies, HSTS, `X-Frame-Options: DENY`, strikte CSP.
- Mandantentrennung über einen `FirmaManager` und eine Middleware, die `request.firma` aus der Mitgliedschaft setzt. Jede View holt Objekte nur mit `firma=request.firma`. Ein generischer Test iteriert alle URL-Muster mit `pk` und prüft 404 für fremde Objekte.
- Geheimnisse (API-Schlüssel, TOTP, SMTP) mit `MultiFernet` verschlüsselt; Schlüssel aus Umgebungsvariablen, Rotation dokumentiert.
- Rate-Limits je IP und je Konto für Login, 2FA, Passwort-Reset, Registrierung, Webhooks.
- Belegpostfach: Whitelist der Absender **und** Prüfung des `Authentication-Results`-Headers (DKIM pass oder SPF pass mit Alignment). Anhänge max. 10 je Mail, je 25 MB, Gesamtgröße 50 MB.
- Uploads: MIME-Prüfung per Inhalt, nicht per Endung; nie ausführen; außerhalb des Webroots speichern.
- Webhooks: Signaturprüfung, Token im Pfad, Payload nur als Hinweis, Daten immer nachladen.
- Export: CSV-Injection-Schutz (Zellen, die mit `= + - @` beginnen, mit `'` präfixen).

## Datenschutz

- Rollen: Die Firma ist Verantwortliche, wir sind Auftragsverarbeiter. AVV nach Art. 28 DSGVO vor Produktivbetrieb (Inhalt liefert das Team).
- Unterauftragsverarbeiter (in App und AVV auflisten): Hetzner (Hosting, DE), Amazon Web Services EMEA (Bedrock, Frankfurt), Mistral AI (Transkription, EU), EU-SMTP-Anbieter, Lexware (Verbindung im Auftrag der Firma, eigener Vertrag der Firma).
- Datenminimierung gegenüber KI (siehe KI-Pipeline). Keine Nutzung für Training (vertraglich bei Bedrock und Mistral zusichern lassen bzw. prüfen).
- Löschfristen: Audio sofort nach Transkription; Rohdateien 7 Tage; Transkripte und Erfassungen 12 Monate; Spiegeldaten bei Trennung der Verbindung nach 30 Tagen; Protokoll 8 Jahre (Nachweis gegenüber Kunden). Löschjob täglich.
- Nur der Inhaber diktiert. Hinweis in der Aufnahme-Oberfläche: "Keine Kundengespräche aufnehmen."
- Betroffenenrechte: Export und Löschung je Firma per Admin-Kommando.

## Betrieb

- Hetzner Cloud in Nürnberg oder Falkenstein, ein Server mit 4 vCPU / 8 GB, Ubuntu LTS.
- `docker compose`: `web` (Gunicorn), `worker`, `db` (Postgres 16, kein öffentlicher Port), `caddy` (Auto-HTTPS).
- Backups: täglich `pg_dump`, verschlüsselt mit restic auf eine Hetzner Storage Box an anderem Standort, 30 Tage täglich, 12 Monate monatlich. Restore-Probe monatlich, im Betriebshandbuch dokumentiert.
- CI mit GitHub Actions: Lint (ruff), Typen (mypy auf `connectors`, `dunning`, `capture`), Tests, Migrations-Check, Docker-Build. Deploy per Tag von CI aus, nie vom Laptop.
- Abhängigkeiten mit `uv` und Lockfile gepinnt; Dependabot oder Renovate.
- Monitoring: Health-Endpoint (DB, Worker-Lebenszeichen, letzter Abgleich je Verbindung), Uptime-Check von extern, Fehlererfassung mit selbst gehostetem GlitchTip oder Sentry mit EU-Datenhaltung.
- Logs strukturiert (JSON), keine personenbezogenen Inhalte in Logs (nur IDs).
