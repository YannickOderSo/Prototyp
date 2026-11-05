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

## Produktion

`docker-compose.prod.yml` (Caddy, Web, Worker, Postgres, Sicherung mit restic), Vorlage `.env.prod.example`.
Aufsetzen, Ausrollen per Tag, Sicherung, Wiederherstellung, Schlüsselrotation und Störungen:
[`vault/03-Umsetzung/Betriebshandbuch.md`](vault/03-Umsetzung/Betriebshandbuch.md).
`scripts/prod_smoke.sh <image>` prüft den kompletten Stack lokal und in der CI.

## Stand

Siehe [`vault/03-Umsetzung/Fortschritt.md`](vault/03-Umsetzung/Fortschritt.md). Nur gegen Mocks
getestete Teile sind dort ausdrücklich so markiert.
