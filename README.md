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

## Stand

Siehe [`vault/03-Umsetzung/Fortschritt.md`](vault/03-Umsetzung/Fortschritt.md). Nur gegen Mocks
getestete Teile sind dort ausdrücklich so markiert.
