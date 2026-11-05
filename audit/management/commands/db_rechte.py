"""Rechte der App-Rolle in Produktion (Datenmodell.md, Sicherheit-Datenschutz-Betrieb.md).

Migrationen laufen als Eigentümer der Tabellen; Web und Worker verbinden sich als eigene Rolle, die nur
lesen, einfügen, ändern und löschen darf. Kein TRUNCATE (würde den Protokoll-Trigger umgehen), kein
UPDATE auf das Protokoll, keine DDL. Läuft nach jeder Migration (Entrypoint) und ist idempotent.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from psycopg import sql

PROTOKOLL = "audit_protokolleintrag"


def rechte_setzen(rolle: str) -> None:
    r = sql.Identifier(rolle)
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [rolle])
        if cursor.fetchone() is None:
            raise CommandError(f"Rolle {rolle} existiert nicht (siehe docker/db/10-app-rolle.sh)")
        cursor.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(connection.settings_dict["NAME"]), r)
        )
        for befehl in (
            "GRANT USAGE ON SCHEMA public TO {r}",
            "REVOKE CREATE ON SCHEMA public FROM {r}",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {r}",
            "REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM {r}",
            "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO {r}",
            "REVOKE UPDATE ON {p} FROM {r}",
        ):
            cursor.execute(sql.SQL(befehl).format(r=r, p=sql.Identifier(PROTOKOLL)))


class Command(BaseCommand):
    help = "Setzt die Rechte der App-Rolle (ohne TRUNCATE, ohne UPDATE auf das Protokoll). Als Eigentümer ausführen."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("rolle")

    def handle(self, *args: Any, **optionen: Any) -> None:
        rechte_setzen(optionen["rolle"])
        self.stdout.write(f"Rechte für {optionen['rolle']} gesetzt")
