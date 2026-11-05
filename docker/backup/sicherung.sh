#!/usr/bin/env bash
# Tägliche Sicherung der Datenbank mit restic auf die Hetzner Storage Box (anderer Standort).
#
# - pg_dump im Custom-Format, direkt an restic übergeben. Mit --stdin-from-command speichert restic keinen
#   Snapshot, wenn pg_dump fehlschlägt.
# - Verschlüsselt durch restic (Passwort aus RESTIC_PASSWORD_FILE, getrennt vom Server aufbewahren).
# - Aufbewahrung: 30 Tage täglich, 12 Monate monatlich (Sicherheit-Datenschutz-Betrieb.md).
# - Die Dateiablage wird bewusst nicht gesichert: Rohdateien leben höchstens 7 Tage (Datenminimierung).
# - Optional: BACKUP_PING_URL wird bei Erfolg aufgerufen, bei Fehler mit /fail (z. B. Healthchecks).
#
# Benötigt: PGHOST, PGUSER, PGPASSWORD, PGDATABASE, RESTIC_REPOSITORY, RESTIC_PASSWORD_FILE oder RESTIC_PASSWORD.
set -euo pipefail

: "${PGDATABASE:?PGDATABASE fehlt}"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY fehlt}"
TAG="${BACKUP_TAG:-cockpit-db}"
DATEINAME="${BACKUP_DATEINAME:-cockpit.dump}"

melden() {
  if [ -n "${BACKUP_PING_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "${BACKUP_PING_URL}$1" >/dev/null || true
  fi
}
trap 'melden /fail' ERR

echo "Sicherung: Datenbank ${PGDATABASE} → ${RESTIC_REPOSITORY%%@*}…"
restic backup \
  --tag "$TAG" \
  --host cockpit \
  --stdin-filename "$DATEINAME" \
  --stdin-from-command -- \
  pg_dump --format=custom --no-owner --no-privileges --dbname "$PGDATABASE"

echo "Sicherung: Aufbewahrung anwenden (30 täglich, 12 monatlich)"
restic forget --tag "$TAG" --host cockpit --keep-daily 30 --keep-monthly 12 --prune

# Sonntags die Struktur des Repositorys prüfen (schnell, ohne alle Daten zu lesen)
if [ "$(date +%u)" = "7" ] || [ "${BACKUP_PRUEFEN:-0}" = "1" ]; then
  restic check
fi

melden ""
echo "Sicherung: fertig"
