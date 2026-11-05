# Häufige Kommandos. Voraussetzung: uv (https://docs.astral.sh/uv/) und für "dev" Docker Compose.
.PHONY: dev down demo test test-cov lint format typecheck migrations-check e2e check

UV ?= uv

dev:            ## Postgres, Web, Worker und Mailpit lokal starten
	docker compose up --build

down:
	docker compose down

demo:           ## Demo-Daten in den laufenden Stack laden (nach "make dev", einmalig)
	docker compose exec web python manage.py demo_daten

test:           ## Alle Tests außer Playwright
	$(UV) run pytest -m "not e2e"

test-cov:       ## Tests mit Abdeckung (Vorgabe: dunning und capture/rules mindestens 90 %)
	$(UV) run pytest -m "not e2e" --cov --cov-report=term-missing

e2e:            ## Playwright-Tests der drei Hauptwege (390 x 844)
	$(UV) run pytest -m e2e

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck:
	$(UV) run mypy connectors dunning capture

migrations-check:
	$(UV) run python manage.py makemigrations --check --dry-run --settings=cockpit.settings_test

check: lint typecheck migrations-check test
