#!/usr/bin/env bash
# Ernstfall: Datenbank aus einer Sicherung wiederherstellen (Ablauf im Betriebshandbuch).
#
# Aufruf: wiederherstellen.sh <snapshot-id|latest> --ich-habe-web-und-worker-gestoppt
# Vorher: docker compose -f docker-compose.prod.yml stop web worker
# Danach: docker compose -f docker-compose.prod.yml up -d (Web migriert und setzt die Rechte der App-Rolle neu)
#
# Ersetzt den Inhalt von PGDATABASE vollständig. Die Sicherung enthält keine Rechte (--no-privileges);
# die App-Rolle bekommt sie beim nächsten Start von web über `manage.py db_rechte`.
set -euo pipefail

SNAPSHOT="${1:-}"
BESTAETIGUNG="${2:-}"
: "${PGDATABASE:?PGDATABASE fehlt}"
DATEINAME="${BACKUP_DATEINAME:-cockpit.dump}"

if [ -z "$SNAPSHOT" ] || [ "$BESTAETIGUNG" != "--ich-habe-web-und-worker-gestoppt" ]; then
  echo "Aufruf: wiederherstellen.sh <snapshot-id|latest> --ich-habe-web-und-worker-gestoppt" >&2
  exit 2
fi

ARBEIT="$(mktemp -d)"
trap 'rm -f "$ARBEIT/sicherung.dump"; rmdir "$ARBEIT" 2>/dev/null || true' EXIT

restic dump "$SNAPSHOT" "$DATEINAME" >"$ARBEIT/sicherung.dump"
pg_restore --list "$ARBEIT/sicherung.dump" >/dev/null  # Datei lesbar?

# Erst in eine neue Datenbank einspielen, dann tauschen: Schlägt das Einspielen fehl, bleibt die alte unberührt.
NEU="${PGDATABASE}_wiederhergestellt"
dropdb --if-exists "$NEU"
createdb "$NEU"
pg_restore --exit-on-error --no-owner --no-privileges --dbname "$NEU" "$ARBEIT/sicherung.dump"

ALT="${PGDATABASE}_vor_wiederherstellung_$(date -u +%Y%m%d%H%M%S)"
psql --dbname postgres -v ON_ERROR_STOP=1 -v alt="$ALT" -v neu="$NEU" -v db="$PGDATABASE" <<'SQL'
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db' AND pid <> pg_backend_pid();
ALTER DATABASE :"db" RENAME TO :"alt";
ALTER DATABASE :"neu" RENAME TO :"db";
SQL

echo "Wiederhergestellt aus $SNAPSHOT. Alte Datenbank bleibt als $ALT erhalten; nach erfolgreicher Prüfung mit"
echo "  dropdb $ALT"
echo "löschen. Jetzt web und worker starten."
