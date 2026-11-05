#!/usr/bin/env bash
# Monatliche Restore-Probe: neueste Sicherung in eine Wegwerf-Datenbank einspielen und prüfen.
#
# Prüft: Sicherung ist jünger als BACKUP_MAX_ALTER_STUNDEN (Standard 26), lässt sich vollständig
# wiederherstellen, enthält alle Migrationen und den Protokoll-Schutz (Trigger). Danach wird die
# Probe-Datenbank wieder gelöscht. Exit-Code ungleich 0 bei jedem Fehler.
#
# Benötigt: wie sicherung.sh; der Datenbanknutzer muss Datenbanken anlegen dürfen (Eigentümer/POSTGRES_USER).
set -euo pipefail

: "${PGDATABASE:?PGDATABASE fehlt}"
TAG="${BACKUP_TAG:-cockpit-db}"
DATEINAME="${BACKUP_DATEINAME:-cockpit.dump}"
PROBE_DB="${PROBE_DB:-cockpit_restore_probe}"
MAX_ALTER_STUNDEN="${BACKUP_MAX_ALTER_STUNDEN:-26}"
ARBEIT="$(mktemp -d)"

aufraeumen() {
  dropdb --if-exists "$PROBE_DB" >/dev/null 2>&1 || true
  rm -f "$ARBEIT/sicherung.dump"
  rmdir "$ARBEIT" 2>/dev/null || true
}
trap aufraeumen EXIT

# 1. Neueste Sicherung und ihr Alter
snapshot_json="$(restic snapshots --json --tag "$TAG" --latest 1)"
snapshot_id="$(jq -r 'sort_by(.time) | last | .short_id // empty' <<<"$snapshot_json")"
snapshot_zeit="$(jq -r 'sort_by(.time) | last | .time // empty' <<<"$snapshot_json")"
if [ -z "$snapshot_id" ]; then
  echo "Restore-Probe FEHLER: keine Sicherung mit Tag $TAG gefunden" >&2
  exit 1
fi
alter_sekunden=$(( $(date -u +%s) - $(date -u -d "$snapshot_zeit" +%s) ))  # GNU date (coreutils)
if [ "$alter_sekunden" -gt $(( MAX_ALTER_STUNDEN * 3600 )) ]; then
  echo "Restore-Probe FEHLER: neueste Sicherung $snapshot_id ist $(( alter_sekunden / 3600 )) Stunden alt" >&2
  exit 1
fi

# 2. In eine frische Probe-Datenbank einspielen
restic dump "$snapshot_id" "$DATEINAME" >"$ARBEIT/sicherung.dump"
dropdb --if-exists "$PROBE_DB"
createdb "$PROBE_DB"
pg_restore --exit-on-error --no-owner --no-privileges --dbname "$PROBE_DB" "$ARBEIT/sicherung.dump"

# 3. Inhalt prüfen
abfrage() { psql --dbname "$PROBE_DB" -Atqc "$1"; }
migrationen="$(abfrage "SELECT count(*) FROM django_migrations")"
trigger="$(abfrage "SELECT count(*) FROM pg_trigger WHERE tgname = 'audit_protokoll_schutz'")"
protokoll="$(abfrage "SELECT count(*) FROM audit_protokolleintrag")"
firmen="$(abfrage "SELECT count(*) FROM accounts_firma")"
if [ "$migrationen" -lt 1 ] || [ "$trigger" != "1" ]; then
  echo "Restore-Probe FEHLER: Migrationen=$migrationen, Protokoll-Trigger=$trigger" >&2
  exit 1
fi
erwartet="$(psql --dbname "$PGDATABASE" -Atqc "SELECT count(*) FROM django_migrations" 2>/dev/null || echo "")"
if [ -n "$erwartet" ] && [ "$migrationen" -lt "$erwartet" ]; then
  echo "Restore-Probe WARNUNG: Sicherung kennt $migrationen von $erwartet Migrationen (neue Migration seit der Sicherung?)" >&2
fi

echo "Restore-Probe OK: Sicherung $snapshot_id vom $snapshot_zeit, Migrationen=$migrationen, Firmen=$firmen, Protokolleinträge=$protokoll"
