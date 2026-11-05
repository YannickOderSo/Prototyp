#!/bin/sh
# Startpunkt des Containers: "web" (Gunicorn), "worker" (Job-Queue) oder ein beliebiges Kommando.
#
# Produktion: Migrationen laufen mit MIGRATIONS_DATABASE_URL (Eigentümer der Tabellen). Danach bekommt die
# App-Rolle (COCKPIT_DB_APP_ROLLE) ihre Rechte; Web und Worker arbeiten mit DATABASE_URL als App-Rolle.
set -eu

migrieren() {
  if [ -n "${MIGRATIONS_DATABASE_URL:-}" ]; then
    DATABASE_URL="$MIGRATIONS_DATABASE_URL" python manage.py migrate --noinput
    DATABASE_URL="$MIGRATIONS_DATABASE_URL" python manage.py createcachetable
    if [ -n "${COCKPIT_DB_APP_ROLLE:-}" ]; then
      DATABASE_URL="$MIGRATIONS_DATABASE_URL" python manage.py db_rechte "$COCKPIT_DB_APP_ROLLE"
    fi
  else
    python manage.py migrate --noinput
    python manage.py createcachetable
  fi
}

case "${1:-web}" in
  web)
    if [ "${COCKPIT_MIGRATE_ON_START:-1}" = "1" ]; then
      migrieren
    fi
    exec gunicorn cockpit.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout 60 \
      --access-logfile - \
      --forwarded-allow-ips "*"
    ;;
  worker)
    exec python manage.py worker
    ;;
  *)
    exec "$@"
    ;;
esac
