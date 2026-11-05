"""Demo-Daten für die lokale Ansicht: nur mit DEBUG, nichts mit Außenwirkung."""

import pytest
from django.core.management import CommandError, call_command

from capture.models import Erfassung
from dunning.models import Mahnvorschlag
from jobs.models import Job
from ledger.models import Beleg

pytestmark = pytest.mark.django_db


def test_nur_mit_debug(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DJANGO_DEBUG"):
        call_command("demo_daten")


def test_demo_daten(settings, client, mailoutbox):
    settings.DEBUG = True
    call_command("demo_daten")
    assert Beleg.objects.filter(status__in=Beleg.OFFENE_STATUS).count() == 9
    stufen = set(Mahnvorschlag.objects.filter(status="vorgeschlagen").values_list("stufe", flat=True))
    assert stufen == {0, 1}
    erfassung = Erfassung.objects.get()
    assert erfassung.status == "pruefung" and erfassung.blocker  # Sockelleiste ohne Preis
    assert not Job.objects.exists() and mailoutbox == []
    with pytest.raises(CommandError, match="existiert bereits"):
        call_command("demo_daten")
