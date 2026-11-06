"""Demo-Connector: nur mit DEBUG und Demo-Verbindung, keine Anfrage nach außen, Demo lokal durchspielbar."""

import io

import pytest
import respx
from django.core.management import call_command
from pypdf import PdfReader

from accounts.models import Firma, Nutzer
from connectors.demo import DEMO_ORGANISATION, DemoConnector, demo_pdf
from connectors.lexware import LexwareConnector
from connectors.models import Verbindung
from connectors.services import connector_fuer
from dunning.freigabe import freigeben
from dunning.models import Mahnvorschlag
from jobs.models import Job
from jobs.queue import enqueue
from ledger.models import Beleg
from tests.conftest import alle_jobs_ausfuehren

pytestmark = pytest.mark.django_db


def test_nur_mit_debug_und_demo_verbindung(settings, verbindung):
    Verbindung.objects.filter(pk=verbindung.pk).update(organisation_id=DEMO_ORGANISATION)
    verbindung.refresh_from_db()
    settings.DEBUG = True
    assert isinstance(connector_fuer(verbindung), DemoConnector)
    settings.DEBUG = False
    assert isinstance(connector_fuer(verbindung), LexwareConnector)
    settings.DEBUG = True
    Verbindung.objects.filter(pk=verbindung.pk).update(organisation_id="echte-organisation")
    verbindung.refresh_from_db()
    assert isinstance(connector_fuer(verbindung), LexwareConnector)


def test_demo_pdf_ist_gueltig():
    seite = PdfReader(io.BytesIO(demo_pdf("Mahnung demo-1"))).pages[0]
    assert "Mahnung demo-1" in seite.extract_text() and "Demo" in seite.extract_text()


def test_demo_lokal_durchspielen_ohne_anfrage_nach_aussen(settings, worker, mailoutbox):
    settings.DEBUG = True
    call_command("demo_daten")
    firma = Firma.objects.get(name="Malerbetrieb Muster GmbH")
    nutzer = Nutzer.objects.get(email="demo@cockpit.local")
    offen_vorher = Beleg.objects.fuer(firma).filter(status__in=Beleg.OFFENE_STATUS).count()
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        ids = list(Mahnvorschlag.objects.fuer(firma).filter(status="vorgeschlagen").values_list("pk", flat=True))
        freigeben(firma, nutzer, ids)
        enqueue("ledger.nachtabgleich_alle", {})
        alle_jobs_ausfuehren(worker)
        assert router.calls.call_count == 0
    vorschlaege = Mahnvorschlag.objects.fuer(firma).filter(pk__in=ids)
    assert set(vorschlaege.exclude(beleg__quelle="kopie").values_list("status", flat=True)) == {"versendet"}
    # Rechnungskopie: Zahlung aus dem Kontoauszug noch nicht zugeordnet, daher kein Versand (K8)
    gesperrt = vorschlaege.filter(beleg__quelle="kopie")
    assert gesperrt.count() == 1 and gesperrt.get().status == "vorgeschlagen"
    assert len(mailoutbox) == len(ids) - 1
    assert all(name.endswith(".pdf") for m in mailoutbox for name, *_ in m.attachments)
    assert not Job.objects.filter(status="fehler").exists()
    assert Beleg.objects.fuer(firma).filter(status__in=Beleg.OFFENE_STATUS).count() == offen_vorher


def test_demo_angebot_als_entwurf_ohne_anfrage_nach_aussen(settings, worker):
    from capture.models import Erfassung
    from capture.uebertragung import freigeben as erfassung_freigeben

    settings.DEBUG = True
    call_command("demo_daten")
    nutzer = Nutzer.objects.get(email="demo@cockpit.local")
    angebot = Erfassung.objects.get(transkript__contains="Praxis Dr. Sommer")
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        erfassung_freigeben(angebot, nutzer)
        alle_jobs_ausfuehren(worker)
        assert router.calls.call_count == 0
    angebot.refresh_from_db()
    assert angebot.status == "uebertragen" and angebot.ziel_art == "quotation"
