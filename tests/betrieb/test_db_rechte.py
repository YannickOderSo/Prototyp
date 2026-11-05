"""M4-05: App-Rolle in Produktion ohne TRUNCATE und ohne UPDATE auf das Protokoll (Datenmodell.md)."""

import pytest
from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction

from audit.models import Protokolleintrag
from audit.services import protokolliere

pytestmark = pytest.mark.django_db

ROLLE = "cockpit_app_test"


@pytest.fixture
def als_app_rolle(firma):
    """Rolle innerhalb der Testtransaktion anlegen (CREATE ROLE ist transaktional) und Rechte setzen."""
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE ROLE {ROLLE} NOLOGIN")
    call_command("db_rechte", ROLLE)
    protokolliere(firma, "test.vorher")

    class Wechsel:
        def __enter__(self):
            with connection.cursor() as c:
                c.execute(f"SET ROLE {ROLLE}")

        def __exit__(self, *args):
            with connection.cursor() as c:
                c.execute("RESET ROLE")

    return Wechsel()


def _verboten(sql):
    with (
        pytest.raises(DatabaseError, match=r"permission denied|must be owner|keine Berechtigung|muss Eigentümer"),
        transaction.atomic(),
    ):
        with connection.cursor() as cursor:
            cursor.execute(sql)


def test_app_rolle_darf_arbeiten(als_app_rolle, firma):
    with als_app_rolle:
        protokolliere(firma, "test.als_app")
        assert Protokolleintrag.objects.filter(ereignis="test.als_app").exists()
        firma.name = "Neu GmbH"
        firma.save()


def test_app_rolle_ohne_truncate_und_ddl(als_app_rolle):
    with als_app_rolle:
        _verboten("TRUNCATE audit_protokolleintrag")
        _verboten("TRUNCATE ledger_beleg")
        _verboten("CREATE TABLE boese (id int)")
        _verboten("DROP TABLE audit_protokolleintrag")
        _verboten("ALTER TABLE audit_protokolleintrag DISABLE TRIGGER audit_protokoll_schutz")


def test_app_rolle_ohne_update_auf_protokoll(als_app_rolle):
    with als_app_rolle:
        _verboten("UPDATE audit_protokolleintrag SET ereignis = 'x'")


def test_unbekannte_rolle():
    with pytest.raises(CommandError, match="existiert nicht"):
        call_command("db_rechte", "gibt_es_nicht")
