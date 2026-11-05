#!/bin/sh
# Startpunkt des Containers: "web" (Gunicorn), "worker" (Job-Queue) oder ein beliebiges Kommando.
set -eu

case "${1:-web}" in
  web)
    if [ "${COCKPIT_MIGRATE_ON_START:-1}" = "1" ]; then
      python manage.py migrate --noinput
      python manage.py createcachetable
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
