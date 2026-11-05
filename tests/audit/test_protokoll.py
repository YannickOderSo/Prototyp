"""M0-05: Protokoll ist nur anhängend; UPDATE und DELETE scheitern in App und Datenbank."""

from datetime import timedelta

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from audit.models import Protokolleintrag, ProtokollGeschuetzt
from audit.services import protokolliere


@pytest.fixture
def eintrag(firma):
    return protokolliere(firma, "einstellung.geaendert", objekt=firma, daten={"feld": "reply_to"})


def test_protokolliere_schreibt_eintrag(eintrag, firma):
    assert eintrag.pk
    assert eintrag.firma == firma
    assert eintrag.objekt_typ == "accounts.Firma"
    assert eintrag.objekt_id == str(firma.pk)
    assert eintrag.nutzer is None


def test_update_ueber_modell_scheitert(eintrag):
    eintrag.ereignis = "manipuliert"
    with pytest.raises(ProtokollGeschuetzt):
        eintrag.save()


def test_update_ueber_queryset_scheitert(eintrag):
    with pytest.raises(ProtokollGeschuetzt):
        Protokolleintrag.objects.filter(pk=eintrag.pk).update(ereignis="x")


def test_delete_ueber_modell_und_queryset_scheitert(eintrag):
    with pytest.raises(ProtokollGeschuetzt):
        eintrag.delete()
    with pytest.raises(ProtokollGeschuetzt):
        Protokolleintrag.objects.all().delete()


def test_update_per_sql_scheitert_am_trigger(eintrag):
    with pytest.raises(DatabaseError, match="unveraenderlich"), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE audit_protokolleintrag SET ereignis = 'x' WHERE id = %s", [eintrag.pk])
    eintrag.refresh_from_db()
    assert eintrag.ereignis == "einstellung.geaendert"


def test_delete_per_sql_scheitert_am_trigger(eintrag):
    with pytest.raises(DatabaseError, match="8 Jahren"), transaction.atomic(), connection.cursor() as cur:
        cur.execute("DELETE FROM audit_protokolleintrag WHERE id = %s", [eintrag.pk])
    assert Protokolleintrag.objects.filter(pk=eintrag.pk).exists()


def test_delete_nach_acht_jahren_erlaubt(firma):
    alt = Protokolleintrag.objects.create(
        firma=firma, ereignis="alt", zeit=timezone.now() - timedelta(days=365 * 8 + 3)
    )
    with connection.cursor() as cur:
        cur.execute("DELETE FROM audit_protokolleintrag WHERE id = %s", [alt.pk])
    assert not Protokolleintrag.objects.filter(pk=alt.pk).exists()


def test_anonymer_nutzer_wird_als_system_gespeichert(firma):
    from django.contrib.auth.models import AnonymousUser

    eintrag = protokolliere(firma, "x", nutzer=AnonymousUser())
    assert eintrag.nutzer is None
