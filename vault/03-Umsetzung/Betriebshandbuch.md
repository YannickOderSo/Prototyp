# Betriebshandbuch

Für alle, die das Cockpit betreiben: aufsetzen, ausrollen, sichern, wiederherstellen und Störungen beheben. Grundlage sind [[Sicherheit-Datenschutz-Betrieb]] und ADR-005 (nur EU). Stand: M4-06, 5. November 2026.

> Was hier steht, ist mit dem Smoke-Test `scripts/prod_smoke.sh` lokal und in der CI geprüft: Stack mit Caddy, App-Rolle, Health, Sicherung und Restore-Probe mit echtem restic. **Nicht** geprüft sind ein echter Hetzner-Server, eine echte Storage Box, echte Zertifikate von Let's Encrypt, der Deploy-Job per SSH und alle externen Dienste (Lexware, Bedrock, Mistral, SMTP, IMAP). Diese Punkte stehen in der Echtlauf-Checkliste unten.

## 1. Überblick

| Dienst | Aufgabe | Erreichbar |
| --- | --- | --- |
| `caddy` | HTTPS (Let's Encrypt), HSTS, Weiterleitung an `web` | Port 80/443 von außen |
| `web` | Django mit Gunicorn, migriert beim Start | nur intern (Port 8000) |
| `worker` | Job-Queue, Zeitpläne (Abgleich 2:00, Löschfristen 3:30, Vorschläge 5:00, Sammelmails, Belegpostfach) | nur intern |
| `db` | Postgres 16, Daten im Volume `pgdaten` | nur intern |
| `backup` | `sicherung.sh`, `restore_probe.sh`, `wiederherstellen.sh` (Profil `backup`, nur bei Bedarf) | nur intern |

Volumes: `pgdaten` (Datenbank), `dateien` (Rohdateien der Erfassung, höchstens 7 Tage), `caddy_daten` (Zertifikate).

Datenbankrollen:
- Der **Eigentümer** (`POSTGRES_USER`) wird nur für Migrationen genutzt (`MIGRATIONS_DATABASE_URL` im Web-Container).
- Die **App-Rolle** (`COCKPIT_DB_APP_ROLLE`) nutzen Web und Worker. Sie hat kein TRUNCATE, keine DDL und kein UPDATE auf das Protokoll.
- `manage.py db_rechte` setzt die Rechte nach jeder Migration neu (Entrypoint).

## 2. Erstinstallation

1. **Server** bei Hetzner Cloud anlegen: Standort Nürnberg oder Falkenstein, 4 vCPU / 8 GB, Ubuntu LTS.
   - Nur SSH mit Schlüssel, kein Passwort-Login.
   - Firewall: eingehend nur 22 (wenn möglich nur feste IPs), 80 und 443.
   - Automatische Sicherheitsupdates (`unattended-upgrades`).
2. **Docker** installieren (offizielles Paket mit Compose-Plugin). Einen Benutzer `cockpit` anlegen und in die Gruppe `docker` aufnehmen.
3. **Code**: `git clone` des Repositorys nach `/srv/cockpit` und den gewünschten Tag auschecken (`git checkout v1.0.0`).
4. **Umgebung**: `.env.prod.example` nach `/srv/cockpit/.env` kopieren und mit `chmod 600 .env` schützen. Alle Werte stehen in Abschnitt 9.
   - `COCKPIT_FERNET_KEYS` erzeugen mit `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   - `DJANGO_SECRET_KEY` erzeugen mit `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.
   - Passwörter für `POSTGRES_PASSWORD` und `COCKPIT_DB_APP_PASSWORT` zufällig erzeugen.
   - Alle Geheimnisse zusätzlich im Passwort-Manager des Teams ablegen. **Ohne die Fernet-Schlüssel sind gespeicherte Lexware-Schlüssel, SMTP-Passwörter und 2FA-Geheimnisse nach einem Restore unbrauchbar.**
5. **Sicherung vorbereiten**:
   - Ordner `geheim/` anlegen (`chmod 700`).
   - Zufälliges restic-Passwort nach `geheim/restic-passwort` schreiben (auch in den Passwort-Manager).
   - SSH-Schlüssel und `geheim/ssh/config` für die Storage Box ablegen. Beispiel für `config`:
     ```
     Host storagebox
       HostName uXXXXXX.your-storagebox.de
       User uXXXXXX
       Port 23
       IdentityFile /root/.ssh/id_ed25519
     ```
   - Öffentlichen Schlüssel in der Storage Box hinterlegen, `known_hosts` füllen. In `.env` steht `RESTIC_REPOSITORY=sftp:storagebox:/cockpit`.
   - Repository einmalig anlegen: `docker compose -f docker-compose.prod.yml --profile backup run --rm backup restic init`.
6. **Start**: `docker compose -f docker-compose.prod.yml up -d --wait`.
   - Beim allerersten Start legt `docker/db/10-app-rolle.sh` die App-Rolle an.
   - `web` migriert und setzt die Rechte.
   - Caddy holt das Zertifikat. Voraussetzung: der DNS-Eintrag von `COCKPIT_DOMAIN` zeigt auf den Server.
7. **Prüfen**: `curl https://<domain>/healthz` antwortet mit `"status": "ok"`.
   - Steht dort `"basiszins": "warnung"`, den aktuellen Satz eintragen (Abschnitt 6).
8. **Zeitpläne auf dem Host** (Systemd-Timer oder Cron des Benutzers `cockpit`):
   - täglich 1:30 Uhr: `cd /srv/cockpit && docker compose -f docker-compose.prod.yml --profile backup run --rm backup sicherung.sh`
   - monatlich am 1. um 4:00 Uhr: `… run --rm backup restore_probe.sh`. Ergebnis ins Betriebsprotokoll, bei Fehler sofort Abschnitt 4.
9. **Externe Überwachung**:
   - Uptime-Check auf `https://<domain>/healthz` jede Minute, Alarm bei HTTP ≠ 200.
   - Optional ein Heartbeat-Dienst für die Sicherung (`BACKUP_PING_URL`, meldet Erfolg und `/fail`).
10. **Erster Zugang**: `docker compose -f docker-compose.prod.yml exec web python manage.py einladung_erstellen --notiz "Pilot Muster"` erzeugt einen Einladungscode für die Registrierung (Inhaber, mit 2FA).

## 3. Ausrollen (Deploy)

Ausgerollt wird nur per Git-Tag aus der CI, nie vom Laptop.

1. Auf `main` (bzw. dem Release-Zweig) muss die CI grün sein.
2. Tag setzen und pushen: `git tag v1.2.0 && git push origin v1.2.0`.
3. `.github/workflows/release.yml` baut das Image, führt den Smoke-Test aus und veröffentlicht `ghcr.io/<repo>:v1.2.0`.
4. Sind in GitHub die Umgebung `produktion` mit `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_HOST_KEY` (Variablen) und `DEPLOY_SSH_KEY` (Secret) hinterlegt, rollt der Job per SSH aus:
   - Tag auschecken,
   - `COCKPIT_IMAGE` in `.env` setzen,
   - `docker compose pull` und `up -d --wait`.
5. Danach `/healthz` prüfen und in den Logs auf Fehler achten (`docker compose -f docker-compose.prod.yml logs -f --tail 100 web worker`).

**Zurückrollen**:
- Vorigen Tag erneut ausrollen (Tag-Pipeline neu starten oder `COCKPIT_IMAGE` von Hand zurücksetzen und `up -d`).
- Migrationen sind nur vorwärts gedacht. Ein Rückschritt über eine Migration hinweg heißt: Restore der Sicherung vor dem Deploy (Abschnitt 4).

## 4. Sicherung und Wiederherstellung

- **Sicherung** (`docker/backup/sicherung.sh`):
  - täglich `pg_dump` im Custom-Format direkt in restic. Schlägt der Dump fehl, entsteht kein Snapshot und das Skript endet mit Fehler.
  - Aufbewahrung 30 Tage täglich, 12 Monate monatlich. Sonntags zusätzlich `restic check`.
  - Die Dateiablage wird nicht gesichert, weil Rohdateien höchstens 7 Tage leben.
  - Gelöschte Daten verschwinden aus den Sicherungen mit Ablauf der Aufbewahrung (höchstens 12 Monate). Das gehört so in die AVV.
- **Restore-Probe** (`restore_probe.sh`, monatlich): prüft Folgendes:
  - Die neueste Sicherung ist höchstens 26 Stunden alt.
  - Sie lässt sich vollständig in eine Wegwerf-Datenbank einspielen.
  - Migrationen und Protokoll-Trigger sind vorhanden.
  - Danach wird die Probe-Datenbank gelöscht.
- **Ernstfall-Wiederherstellung**:
  1. `docker compose -f docker-compose.prod.yml stop web worker`
  2. Snapshot wählen: `docker compose -f docker-compose.prod.yml --profile backup run --rm backup restic snapshots`
  3. `… run --rm backup wiederherstellen.sh <snapshot-id|latest> --ich-habe-web-und-worker-gestoppt`
     - Spielt erst in eine neue Datenbank ein und tauscht dann.
     - Die alte Datenbank bleibt als `cockpit_vor_wiederherstellung_<zeit>` erhalten.
  4. `docker compose -f docker-compose.prod.yml up -d --wait`. Web migriert und setzt die Rechte der App-Rolle.
  5. Prüfen: `/healthz`, Anmeldung, Postenliste einer Pilotfirma.
  6. Die alte Datenbank erst nach erfolgreicher Prüfung löschen: `docker compose exec db dropdb -U cockpit <name>`.
  7. Den Nachtabgleich für alle Firmen anstoßen, damit der Spiegel wieder aktuell ist:
     `docker compose exec web python manage.py shell -c "from jobs.queue import enqueue; enqueue('ledger.nachtabgleich_alle', {})"`
  - Mahnungen, die nach dem Zeitpunkt der Sicherung versendet wurden, fehlen im Cockpit, stehen aber in Lexware. Vor der nächsten Freigabe die Vorschläge mit Lexware abgleichen. Der Frische-Check vor jedem Versand verhindert Mahnungen bezahlter Rechnungen.
- **Totalverlust des Servers**: neuen Server nach Abschnitt 2 aufsetzen, mit `.env`, `geheim/` und Fernet-Schlüsseln aus dem Passwort-Manager. Dann wiederherstellen wie oben, ohne Schritt 1.

## 5. Schlüsselrotation

- **Fernet-Schlüssel** (`COCKPIT_FERNET_KEYS`):
  1. Neuen Schlüssel erzeugen und **vorne** einfügen (`neu,alt`).
  2. `docker compose … up -d` (Web und Worker lesen beide Schlüssel).
  3. `docker compose exec web python manage.py schluessel_rotieren` verschlüsselt alle Lexware-Schlüssel, SMTP-Passwörter und 2FA-Geheimnisse neu.
  4. `… schluessel_rotieren --pruefen` muss „0 mit altem Schlüssel“ melden.
  5. Alten Schlüssel aus `.env` entfernen, `up -d`, Passwort-Manager aktualisieren.
  - Turnus: jährlich und sofort bei Verdacht.
- **Django-Schlüssel** (`DJANGO_SECRET_KEY`):
  - Neuen Wert setzen, den alten nach `DJANGO_SECRET_KEY_FALLBACKS` verschieben, `up -d`.
  - Nach 14 Tagen (Ablauf offener Sitzungen und Einladungslinks) den Fallback entfernen.
  - Bei Verdacht auf Kompromittierung sofort ohne Fallback tauschen. Alle Nutzer müssen sich dann neu anmelden.
- **Datenbankpasswörter**:
  - `ALTER ROLE … PASSWORD …` als Eigentümer ausführen (`docker compose exec db psql -U cockpit`).
  - Danach `.env` anpassen und `up -d`.
- **restic**: `restic key add` ausführen, das neue Passwort nach `geheim/restic-passwort` schreiben, dann `restic key remove <alte-id>`.
- **Lexware-Schlüssel der Kunden**:
  - Der Kunde erzeugt in Lexware einen neuen Schlüssel und trägt ihn unter Einstellungen → Lexware Office ein.
  - Ein Schlüssel eines anderen Lexware-Kontos wird abgelehnt, solange die alte Verbindung besteht.
- **SMTP, Mistral, AWS, Sentry, Zustell-Webhook-Token**: beim Anbieter neu erzeugen, in `.env` tauschen, `up -d`.

## 6. Regelmäßige Pflege

- **Basiszins** (§ 247 BGB), halbjährlich zum 1. Januar und 1. Juli:
  - Die Bundesbank veröffentlicht den Satz Ende Dezember bzw. Ende Juni.
  - Eintragen mit `docker compose exec web python manage.py basiszins_setzen 2027-01-01 1.27 --quelle "Deutsche Bundesbank, Mitteilung vom 30.12.2026"`. Negative Sätze mit Punkt schreiben, z. B. `-0.88`.
  - Ohne Satz für das laufende Halbjahr berechnet das Cockpit **keine** Zinsen (schuldnergünstig) und `/healthz` meldet `"basiszins": "warnung"`.
  - Einen falsch eingetragenen Satz korrigiert `--korrigieren`. Bereits freigegebene Mahnungen ändern sich dadurch nicht.
- **Abhängigkeiten**:
  - Renovate oder Dependabot öffnet Pull Requests. Sicherheitsupdates zeitnah ausrollen.
  - Postgres-Minor-Updates mit `docker compose pull db && up -d`.
  - Ein Postgres-Major-Update nur mit Dump und Restore.
- **Löschfristen** laufen automatisch täglich um 3:30 Uhr (`audit.loeschfristen`). Ergebnis je Firma im Protokoll (`loeschfristen.ausgefuehrt`).
- **Betroffenenrechte**:
  - Export: `docker compose exec web python manage.py firma_export <firma_id> /tmp/export.zip`, danach `docker compose cp web:/tmp/export.zip .` und im Container löschen.
  - Löschung: `manage.py firma_loeschen <firma_id> --bestaetigen "<Firmenname>"`. Vorher exportieren. Das Protokoll bleibt 8 Jahre als Nachweis.

## 7. Störungen

**Health meldet `fehler` (HTTP 503)**
- `datenbank`:
  - Prüfen: `docker compose ps db`, `docker compose logs db`, freier Plattenplatz (`df -h`).
  - Ist die Datenbank beschädigt: Restore (Abschnitt 4).
- `worker`:
  - Prüfen: `docker compose ps worker` und `docker compose logs --tail 200 worker`.
  - Neustart mit `docker compose restart worker`.
  - Hängende Jobs gibt der Worker nach 5 Minuten selbst frei.

**Health meldet `warnung` (HTTP 200)**
- `warteschlange`: Jobs warten länger als 15 Minuten.
  - Meist ist der Worker überlastet oder ein externer Dienst langsam.
  - Rückstand ansehen: `docker compose exec web python manage.py shell -c "from django.db.models import Count; from jobs.models import Job; print(list(Job.objects.filter(status='wartet').values('typ').annotate(n=Count('id'))))"`
- `abgleich`: eine Verbindung wurde seit 26 Stunden nicht abgeglichen, ein Erstimport hängt oder eine Verbindung steht auf Fehler. Weiter bei „Störung Lexware“.
- `basiszins`: Abschnitt 6.

**Störung Lexware**
- Woran man sie erkennt:
  - Health meldet `abgleich: warnung`.
  - Bei der Firma steht unter Einstellungen → Lexware Office ein Fehler.
  - In den Logs häufen sich `ConnectorFehler`, 429 oder 5xx.
- Was die App selbst tut:
  - Drosselung auf 2 Anfragen je Sekunde.
  - 429 und 5xx bis zu fünfmal mit Backoff wiederholen (`Retry-After` wird beachtet).
  - Jobs mit Backoff erneut einplanen (30 s · 2ⁿ, höchstens 1 h).
- Was die Störung bewirkt: Vor jedem Mahnversand prüft der Frische-Check den Zahlstatus in Lexware. Ist Lexware nicht erreichbar, wird **nicht** versendet. Der Vorschlag bleibt im Fehler mit Neuversuch.
- Vorgehen:
  1. Statusseite und Entwicklerportal von Lexware prüfen, ob die API gestört ist.
  2. Bei 401/403 ist der Schlüssel widerrufen oder abgelaufen. Der Kunde muss neu verbinden (Einstellungen → Lexware Office); die Verbindung steht auf „Fehler“.
  3. Bei einer längeren Störung die Firmen über die Sammelmail bzw. telefonisch informieren. Mahnungen gehen erst nach der Störung raus, der Frische-Check läuft dann erneut.
  4. Nach der Störung prüfen, ob der Nachtabgleich gelaufen ist. Sonst von Hand anstoßen (Abschnitt 4, Schritt 7).
  5. Webhooks: Lexware stellt erneut zu. Fehlen Ereignisse, holt der Nachtabgleich die Änderungen nach (`updatedDateFrom` minus 1 Tag).

**Mails kommen nicht an**
- Bounces erreichen den Zustell-Webhook `/hooks/zustellung/<ZUSTELLUNG_WEBHOOK_TOKEN>/`. Der Vorschlag zeigt dann „Zustellung fehlgeschlagen“ und die Firma wird informiert.
- SMTP-Zugang der Plattform prüfen. Firmen mit eigenem SMTP sehen ihren Zugang unter Einstellungen → E-Mail-Versand und können dort eine Testmail senden.

**KI oder Transkription gestört (Bedrock, Mistral)**
- Erfassungen gehen nach drei Versuchen auf „Fehler“ mit Knopf „Erneut versuchen“. Es wird nichts in Lexware angelegt.
- Kostenlimit je Firma und Monat: `KI_LIMIT_VORGAENGE_MONAT`, `KI_LIMIT_TOKENS_MONAT`.
- Es gibt **keinen** Ausweich-Endpunkt außerhalb der EU, auch nicht übergangsweise (Systemchecks `cockpit.E001`–`E003`).

**Belegpostfach nimmt nichts an**
- Abgelehnte Mails stehen im Protokoll der Firma (`belegpostfach.abgelehnt`, mit Grund) und als `PostfachEingang`.
- Häufige Ursachen:
  - Absender nicht in der Whitelist.
  - DKIM/SPF nicht bestanden.
  - `BELEGPOSTFACH_AUTHSERV_ID` passt nicht zum `Authentication-Results`-Kopf des eigenen Mailservers.

## 8. Logs und Fehlererfassung

- Logs gehen als JSON auf stdout, mit Rotation (10 MB × 5 je Container). Sie enthalten nur IDs, keine Inhalte. Ansehen mit `docker compose -f docker-compose.prod.yml logs -f web worker`.
- Fehlererfassung über `SENTRY_DSN`:
  - Erlaubt sind GlitchTip, selbst gehostet in der EU, oder Sentry mit EU-Datenhaltung (`*.de.sentry.io`). Ein US-DSN bricht den Start ab (Systemcheck `cockpit.E004`).
  - Gesendet werden keine Request-Inhalte, Cookies, Header, Query-Strings oder lokale Variablen.
  - Endgültig fehlgeschlagene Jobs erscheinen dort als Fehler.

## 9. Benötigte Zugänge für den Echtlauf

| Variable | Zweck | Woher |
| --- | --- | --- |
| `COCKPIT_IMAGE` | Image der App (per Tag gebaut) | GHCR des Repositorys, nach dem Release-Workflow |
| `COCKPIT_DOMAIN`, `COCKPIT_BASIS_URL`, `DJANGO_ALLOWED_HOSTS` | Domain des Cockpits, Links in Mails, Lexware-Webhook-URL | Domain beim Registrar; DNS-A/AAAA-Eintrag auf den Server |
| `COCKPIT_ACME_EMAIL` | Kontakt für Let's Encrypt | Betriebs-Postfach des Teams |
| `DJANGO_SECRET_KEY` (+ `DJANGO_SECRET_KEY_FALLBACKS`) | Sitzungen, Signaturen | selbst erzeugen (Abschnitt 2) |
| `COCKPIT_FERNET_KEYS` | Verschlüsselung gespeicherter Geheimnisse | selbst erzeugen, im Passwort-Manager sichern |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Datenbank-Eigentümer (nur Migrationen) | selbst festlegen |
| `COCKPIT_DB_APP_ROLLE`, `COCKPIT_DB_APP_PASSWORT` | App-Rolle für Web und Worker | selbst festlegen |
| Lexware-API-Schlüssel (je Firma, **nicht** in `.env`) | Lesen der Posten, Entwürfe und Mahnungen anlegen | Pilotbetrieb mit Lexware Office **XL** erzeugt ihn im Lexware-Entwicklerportal und trägt ihn in der App ein |
| `LEXWARE_BASIS_URL` | API-Adresse (Standard `https://api.lexware.io`) | nur ändern, wenn Lexware es vorgibt |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Claude über Amazon Bedrock (Extraktion) | AWS-Konto des Teams, IAM-Nutzer nur mit `bedrock:InvokeModel` in `eu-central-1`; Modellzugang für Claude in der Bedrock-Konsole freischalten; AVV/DPA mit AWS EMEA |
| `BEDROCK_REGION`, `BEDROCK_MODELL` | EU-Region und EU-Inferenzprofil | `eu-central-1`, Profil-ID mit Präfix `eu.` aus der Bedrock-Konsole (offene Frage zur genauen ID) |
| `MISTRAL_API_KEY`, `MISTRAL_MODELL` | Transkription der Sprachmemos (Voxtral) | Mistral-Konsole (La Plateforme), Organisation mit EU-Verarbeitung; AVV mit Mistral AI |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | Versand der Erinnerungen, Mahnungen, Sammelmails und Systemmails | EU-SMTP-Anbieter mit AVV (Auswahl offen, siehe Offene Fragen); SPF, DKIM und DMARC für die Absenderdomain einrichten |
| `ZUSTELLUNG_WEBHOOK_TOKEN` | Bounces und Zustellfehler vom SMTP-Anbieter | selbst erzeugen, beim Anbieter als Webhook `https://<domain>/hooks/zustellung/<token>/` eintragen; Adapter für dessen Format fehlt noch |
| `BELEGPOSTFACH_ADRESSE`, `BELEGPOSTFACH_IMAP_HOST`, `BELEGPOSTFACH_IMAP_PORT`, `BELEGPOSTFACH_IMAP_BENUTZER`, `BELEGPOSTFACH_IMAP_PASSWORT`, `BELEGPOSTFACH_IMAP_ORDNER` | Belegpostfach (`belege+<token>@…`) | EU-Mailanbieter mit Plus-Adressierung und IMAP |
| `BELEGPOSTFACH_AUTHSERV_ID` | Nur DKIM/SPF-Ergebnisse des eigenen Mailservers zählen | Kennung im `Authentication-Results`-Kopf einer Testmail an das Postfach |
| `SENTRY_DSN`, `SENTRY_UMGEBUNG` | Fehlererfassung | GlitchTip selbst gehostet (EU) oder Sentry-Projekt mit Datenhaltung EU (`*.de.sentry.io`) |
| `RESTIC_REPOSITORY`, `geheim/restic-passwort`, `geheim/ssh/` | Verschlüsselte Sicherung | Hetzner Storage Box an anderem Standort (SFTP, Port 23); Passwort selbst erzeugen |
| `BACKUP_PING_URL` (optional) | Meldung, dass die Sicherung lief | Heartbeat-Dienst in der EU (z. B. Healthchecks selbst gehostet) |
| Uptime-Check (außerhalb der App) | Alarm bei `/healthz` ≠ 200 | Monitoring-Dienst in der EU, Alarm an das Team |
| GitHub: Umgebung `produktion` mit `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_HOST_KEY`, Secret `DEPLOY_SSH_KEY` | Ausrollen per Tag | Server-Benutzer `cockpit` mit eigenem Deploy-Schlüssel |
| Hetzner-Konto | Server (Nürnberg/Falkenstein) und Storage Box | Hetzner Cloud Console; AVV mit Hetzner |

Optionale Stellschrauben: `KI_LIMIT_VORGAENGE_MONAT`, `KI_LIMIT_TOKENS_MONAT`, `GUNICORN_WORKERS`, `LOG_LEVEL`, `DATABASE_CONN_MAX_AGE`, `EMAIL_TIMEOUT`.

## 10. Echtlauf-Checkliste

Vor dem ersten Pilotbetrieb, in dieser Reihenfolge. Alles hier ist bisher nur mit Attrappen getestet.

- [ ] Server und Storage Box bei Hetzner, AVV abgeschlossen; Domain mit DNS; Zertifikat von Let's Encrypt kommt an.
- [ ] Sicherung läuft nachts, erste Restore-Probe auf dem Server erfolgreich (`restore_probe.sh`).
- [ ] Uptime-Check alarmiert, wenn `worker` gestoppt wird (Test: `docker compose stop worker`, Alarm binnen 5 Minuten, danach wieder starten).
- [ ] Fehlererfassung empfängt einen Testfehler (z. B. einen Job mit unbekanntem Typ einplanen).
- [ ] SMTP-Anbieter gewählt (ADR), SPF/DKIM/DMARC eingerichtet, Testmail kommt an und landet nicht im Spam; Bounce-Webhook liefert an `/hooks/zustellung/…` (Adapter für das Anbieterformat schreiben).
- [ ] Lexware: Pilot mit XL-Tarif verbindet sich. Prüfen:
  - Erstimport ist binnen 2 Minuten nutzbar.
  - Ein Webhook kommt an (Signatur geprüft).
  - Der Nachtabgleich läuft.
  - Eine Mahnung mit nur einer Textposition wird von Lexware angenommen (offene Frage).
  - Es wird nie `finalize` gesendet; die Entwürfe liegen in Lexware als Entwurf.
- [ ] Bedrock: Modellzugang in `eu-central-1` freigeschaltet, EU-Profil-ID bestätigt. `manage.py ki_testfaelle` mit echten Schlüsseln erreicht die Abnahme-Quote.
- [ ] Mistral: Transkription eines echten Sprachmemos funktioniert, Audio wird danach gelöscht.
- [ ] Belegpostfach: Testmail mit DKIM wird angenommen, gefälschter Absender abgelehnt.
- [ ] Mahntexte, Zinslogik und Verzugstabelle durch Anwalt/Steuerberater geprüft (M4-07, Offene Fragen).
- [ ] Datenschutz: AVV-Vorlage, Liste der Unterauftragsverarbeiter in App und AVV, Datenschutzerklärung und Impressum mit echten Daten (Rechtstexte unter `/rechtliches/`).
- [ ] Basiszins für das laufende Halbjahr eingetragen (`/healthz` ohne `basiszins: warnung`).
