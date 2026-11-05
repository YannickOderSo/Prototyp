#!/usr/bin/env bash
# Smoke-Test des Produktions-Stacks (docker-compose.prod.yml) mit Platzhalter-Geheimnissen.
#
# Prüft: Datenbank-Init legt die App-Rolle an, Web migriert als Eigentümer und setzt die Rechte,
# Web und Worker laufen als App-Rolle, /healthz ist über Caddy per HTTPS erreichbar und meldet "ok",
# die App-Rolle darf kein TRUNCATE, Sicherung und Restore-Probe laufen mit echtem restic.
#
# Aufruf: scripts/prod_smoke.sh <app-image>   (z. B. cockpit:ci aus dem Docker-Build)
set -euo pipefail

IMAGE="${1:?Aufruf: prod_smoke.sh <app-image>}"
cd "$(dirname "$0")/.."
PROJEKT="cockpit-smoke-$$"
ARBEIT="$(mktemp -d)"
ENV_DATEI="$ARBEIT/smoke.env"

zufall() { python3 -c "import secrets; print(secrets.token_urlsafe(24))"; }
fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }

cat >"$ENV_DATEI" <<EOF
COCKPIT_IMAGE=$IMAGE
COCKPIT_DOMAIN=localhost
COCKPIT_ACME_EMAIL=betrieb@example.org
COCKPIT_BASIS_URL=https://localhost
DJANGO_ALLOWED_HOSTS=localhost
DJANGO_SECRET_KEY=$(zufall)$(zufall)
COCKPIT_FERNET_KEYS=$(fernet)
POSTGRES_USER=cockpit
POSTGRES_PASSWORD=$(zufall)
POSTGRES_DB=cockpit
COCKPIT_DB_APP_ROLLE=cockpit_app
COCKPIT_DB_APP_PASSWORT=$(zufall)
EMAIL_HOST=localhost
RESTIC_REPOSITORY=/repo
EOF

# Eigene Umgebungsdatei und eigener Geheimnis-Ordner: eine vorhandene .env bleibt unberührt
mkdir -p "$ARBEIT/geheim/ssh"
zufall >"$ARBEIT/geheim/restic-passwort"
export COCKPIT_ENV_DATEI="$ENV_DATEI" COCKPIT_GEHEIM="$ARBEIT/geheim"

dc() { docker compose -p "$PROJEKT" --env-file "$ENV_DATEI" -f docker-compose.prod.yml -f docker-compose.smoke.yml "$@"; }

aufraeumen() {
  status=$?
  if [ "$status" -ne 0 ]; then
    dc ps -a || true
    dc logs --no-color --tail 80 || true
  fi
  dc --profile backup down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$ENV_DATEI" "$ARBEIT/geheim/restic-passwort"
  rmdir "$ARBEIT/geheim/ssh" "$ARBEIT/geheim" "$ARBEIT" 2>/dev/null || true
  exit "$status"
}
trap aufraeumen EXIT

echo "== Stack starten"
dc up -d --wait --wait-timeout 240 db web worker caddy

echo "== Health über Caddy (HTTPS, interne CA für localhost)"
PORT="$(dc port caddy 443 | sed 's/.*://')"
for _ in $(seq 1 30); do
  if antwort="$(curl -sk --resolve "localhost:$PORT:127.0.0.1" "https://localhost:$PORT/healthz")" \
    && grep -q '"status": "ok"' <<<"$antwort"; then
    break
  fi
  sleep 2
done
echo "$antwort"
grep -q '"status": "ok"' <<<"$antwort"

echo "== Anmeldeseite erreichbar, Sicherheitsheader gesetzt"
kopf="$(curl -sk -o /dev/null -D - --resolve "localhost:$PORT:127.0.0.1" "https://localhost:$PORT/konto/anmelden/")"
grep -qi "^strict-transport-security:" <<<"$kopf"
grep -qi "^content-security-policy:" <<<"$kopf"

echo "== App-Rolle: arbeitet, aber kein TRUNCATE"
dc exec -T web python manage.py shell -c "from django.db import connection; c = connection.cursor(); c.execute('select current_user'); assert c.fetchone()[0] == 'cockpit_app'"
APP_PW="$(grep ^COCKPIT_DB_APP_PASSWORT "$ENV_DATEI" | cut -d= -f2-)"
als_app() { dc exec -T -e PGPASSWORD="$APP_PW" db psql -h 127.0.0.1 -U cockpit_app -d cockpit -v ON_ERROR_STOP=1 -Atc "$1" 2>&1; }
als_app "SELECT count(*) FROM audit_protokolleintrag" >/dev/null
if ausgabe="$(als_app "TRUNCATE audit_protokolleintrag")"; then
  echo "FEHLER: App-Rolle darf TRUNCATE" >&2
  exit 1
fi
grep -Eq "must be owner|permission denied" <<<"$ausgabe" || { echo "Unerwartet: $ausgabe" >&2; exit 1; }

echo "== Sicherung und Restore-Probe mit echtem restic"
if ! docker image inspect cockpit-backup:lokal >/dev/null 2>&1; then
  dc --profile backup build backup
fi
dc --profile backup run --rm backup restic init
dc --profile backup run --rm -e BACKUP_PRUEFEN=1 backup sicherung.sh
dc --profile backup run --rm backup restore_probe.sh

echo "Smoke-Test OK"
