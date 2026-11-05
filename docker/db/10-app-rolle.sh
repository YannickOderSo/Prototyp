#!/bin/sh
# Läuft einmal beim ersten Start der Datenbank (docker-entrypoint-initdb.d).
# Legt die App-Rolle an, mit der Web und Worker arbeiten. Eigentümer der Tabellen bleibt POSTGRES_USER,
# der nur für Migrationen genutzt wird. Die Tabellenrechte setzt `manage.py db_rechte` nach jeder Migration.
set -eu
: "${COCKPIT_DB_APP_ROLLE:?COCKPIT_DB_APP_ROLLE fehlt}"
: "${COCKPIT_DB_APP_PASSWORT:?COCKPIT_DB_APP_PASSWORT fehlt}"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v rolle="$COCKPIT_DB_APP_ROLLE" -v passwort="$COCKPIT_DB_APP_PASSWORT" -v db="$POSTGRES_DB" <<'SQL'
CREATE ROLE :"rolle" LOGIN PASSWORD :'passwort' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
