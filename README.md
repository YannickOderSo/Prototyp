# Forderungs- und Abrechnungs-Cockpit (Arbeitstitel)

Aufsatz auf Lexware Office für Handwerksbetriebe und kleine Dienstleister: Forderungs-Cockpit,
Mahnautomatik mit Freigabe und Erfassung per Sprache, Foto oder Mail als Entwurf im Bestandstool.

Die verbindliche Spezifikation liegt in [`vault/`](vault/00-Start-hier.md). Arbeitsanweisungen für
Agenten stehen in [`CLAUDE.md`](CLAUDE.md).

## Lokal starten

```bash
uv sync                      # Abhängigkeiten aus uv.lock
cp .env.example .env         # Werte anpassen, Fernet-Schlüssel erzeugen
make dev                     # Postgres, Web und Worker per Docker Compose
make test                    # Tests (pytest)
```

Ohne Docker: Postgres 16 lokal bereitstellen, `DATABASE_URL` setzen, dann
`uv run python manage.py migrate` und `uv run python manage.py runserver`.

## Demo lokal ansehen

Voraussetzung: Docker Desktop (oder Docker mit Compose-Plugin) und Git.

```bash
git clone https://github.com/YannickOderSo/Prototyp.git && cd Prototyp
git checkout build/mvp
docker compose up --build -d      # Postgres, Web, Worker, Mailpit
docker compose exec web python manage.py demo_daten
```

Dann im Browser <http://localhost:8000> öffnen (am besten in der Handy-Ansicht der Entwicklerwerkzeuge)
und mit `demo@cockpit.local` / `Demo-Cockpit-2026!` anmelden. Beim ersten Anmelden wird die
Zwei-Faktor-Anmeldung eingerichtet: QR-Code mit einer Authenticator-App scannen (z. B. Google oder
Microsoft Authenticator) oder den angezeigten Schlüssel eintippen. Mails landen in Mailpit unter
<http://localhost:8025>.

Die Demo spricht mit keinem externen Dienst: Die Demo-Verbindung nutzt nur mit `DJANGO_DEBUG=true` einen
Demo-Connector, der ausschließlich auf der lokalen Datenbank arbeitet. Freigegebene Mahnungen gehen als Mail mit
Demo-PDF an Mailpit; freigegebene Entwürfe bekommen eine Demo-ID statt eines echten Lexware-Entwurfs. Neue
Sprachmemos und Uploads brauchen echte Mistral- und AWS-Zugänge (`.env`) und enden ohne sie mit „Fehler“.
Für einen frischen Stand: `docker compose down -v` und neu starten.

## Produktion

`docker-compose.prod.yml` (Caddy, Web, Worker, Postgres, Sicherung mit restic), Vorlage `.env.prod.example`.
Aufsetzen, Ausrollen per Tag, Sicherung, Wiederherstellung, Schlüsselrotation und Störungen:
[`vault/03-Umsetzung/Betriebshandbuch.md`](vault/03-Umsetzung/Betriebshandbuch.md).
`scripts/prod_smoke.sh <image>` prüft den kompletten Stack lokal und in der CI.

## Stand

Siehe [`vault/03-Umsetzung/Fortschritt.md`](vault/03-Umsetzung/Fortschritt.md). Nur gegen Mocks
getestete Teile sind dort ausdrücklich so markiert.
