# Sicherheit, Datenschutz, Betrieb

## Sicherheit

- Django-Standardschutz: CSRF, Autoescaping, Secure/HttpOnly-Cookies, HSTS, `X-Frame-Options: DENY`, strikte CSP.
- Mandantentrennung über einen `FirmaManager` und eine Middleware, die `request.firma` aus der Mitgliedschaft setzt. Jede View holt Objekte nur mit `firma=request.firma`. Ein generischer Test iteriert alle URL-Muster mit `pk` und prüft 404 für fremde Objekte.
  Umgesetzt (M1-04): `accounts/mandant.py` mit `FirmaModel`, `FirmaManager.fuer(firma)` und `hole_oder_404()`. Der Test `tests/test_mandantentrennung.py` sammelt alle URL-Muster mit Parametern aus dem Resolver; jedes braucht einen Eintrag in `tests/idor_faelle.py` (Fabrik für ein Objekt einer fremden Firma, GET und POST müssen 404 liefern, Gegenprobe mit eigener Firma) oder eine begründete Ausnahme. Neue URLs ohne Eintrag lassen CI scheitern. Fremde Objekte ergeben immer 404, nie 403, damit ihre Existenz nicht verraten wird.
- Geheimnisse (API-Schlüssel, TOTP, SMTP) mit `MultiFernet` verschlüsselt; Schlüssel aus Umgebungsvariablen, Rotation dokumentiert.
- Rate-Limits je IP und je Konto für Login, 2FA, Passwort-Reset, Registrierung, Webhooks.
  Umgesetzt (M1-03): django-ratelimit mit festen 15-Minuten-Fenstern im Datenbank-Cache (gilt über alle Prozesse). Ab 10 Fehlversuchen je IP oder je Konto antwortet die App mit 429, bevor Passwort oder Code geprüft werden. Passwort-Reset und Registrierung zählen jede Anfrage. Hinter Caddy wird die Client-IP aus dem letzten Eintrag von `X-Forwarded-For` gelesen (`COCKPIT_HINTER_PROXY=true`, nur wenn die App ausschließlich über Caddy erreichbar ist).
- Belegpostfach: Whitelist der Absender **und** Prüfung des `Authentication-Results`-Headers (DKIM pass oder SPF pass mit Alignment). Anhänge max. 10 je Mail, je 25 MB, Gesamtgröße 50 MB.
  Umgesetzt (M3-09, `capture/postfach.py`): Sammelpostfach `BELEGPOSTFACH_ADRESSE`, je Firma eine Plus-Adresse mit zufälligem Token (neu erzeugbar). Gezählt wird nur der oberste `Authentication-Results`-Kopf mit der authserv-id des eigenen Mailservers (`BELEGPOSTFACH_AUTHSERV_ID`); ohne diese Einstellung wird jede Mail abgelehnt. DKIM `header.d` oder SPF `smtp.mailfrom` muss zur From-Domain passen (gleiche Domain oder Subdomain, vereinfachtes Relaxed Alignment ohne Public-Suffix-Liste). Abgelehnte Mails werden protokolliert (nur Domain, keine Adresse). IMAP über TLS mit 30 s Timeout, höchstens 50 Mails je Lauf alle 5 Minuten, jede Mail für sich; doppelte Message-IDs werden übersprungen. Angenommene Mails gehen ohne Textprüfung direkt in die Extraktion; geprüft wird in der Prüfansicht.
- Uploads: MIME-Prüfung per Inhalt, nicht per Endung; nie ausführen; außerhalb des Webroots speichern.
- Webhooks: Signaturprüfung, Token im Pfad, Payload nur als Hinweis, Daten immer nachladen.
- Export: CSV-Injection-Schutz (Zellen, die mit `= + - @` beginnen, mit `'` präfixen).
  Umgesetzt (M4-02, `reports/export.py`): ZIP mit `vorschlaege.csv`, `versaende.csv`, `protokoll.csv`, `erfassungen.csv` (Semikolon, UTF-8 mit BOM); zusätzlich Tab und CR am Zellanfang geschützt. Nur der Inhaber exportiert (Seite „Berichte“), jeder Export wird protokolliert. Für Betroffenenrechte: `manage.py firma_export <firma_id> <datei>`.

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
