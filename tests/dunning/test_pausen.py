"""M2-08: Pausen für Kunde und Beleg (D8). Pausierte Posten erzeugen keine Vorschläge."""

from datetime import timedelta

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.models import Mahnvorschlag
from dunning.vorschlaege import vorschlagslauf
from tests.dunning.conftest import HEUTE

pytestmark = pytest.mark.django_db


def test_beleg_pausieren_zieht_vorschlag_zurueck_und_verhindert_neue(client_freigeber, firma, posten, heute):
    beleg = posten(tage=10)
    vorschlagslauf(firma)
    assert Mahnvorschlag.objects.filter(beleg=beleg).exists()
    bis = HEUTE + timedelta(days=14)
    antwort = client_freigeber.post(
        reverse("ledger:beleg_pause", args=[beleg.pk]), {"mahnpause_bis": bis.isoformat()}, follow=True
    )
    assert "1 offene Vorschläge zurückgezogen" in antwort.content.decode()
    beleg.refresh_from_db()
    assert beleg.mahnpause_bis == bis
    assert not Mahnvorschlag.objects.filter(beleg=beleg).exists()
    assert vorschlagslauf(firma).neu == []
    assert Protokolleintrag.objects.filter(ereignis="beleg.pause_gesetzt").exists()
    # Pause aufheben → am nächsten Lauf wieder Vorschlag
    client_freigeber.post(reverse("ledger:beleg_pause", args=[beleg.pk]), {"mahnpause_bis": ""})
    assert len(vorschlagslauf(firma).neu) == 1
    assert Protokolleintrag.objects.filter(ereignis="beleg.pause_aufgehoben").exists()


def test_pause_endet_nach_dem_datum(firma, posten, heute):
    posten(tage=10, mahnpause_bis=HEUTE)
    assert vorschlagslauf(firma).neu == []
    assert len(vorschlagslauf(firma, HEUTE + timedelta(days=1)).neu) == 1


def test_kunde_pausieren(client_inhaber, firma, posten, heute):
    a = posten(tage=10)
    b = posten(tage=12, kontakt=a.kontakt)
    vorschlagslauf(firma)
    assert Mahnvorschlag.objects.count() == 2
    client_inhaber.post(
        reverse("ledger:kontakt_pause", args=[a.kontakt.pk]),
        {"mahnpause_bis": (HEUTE + timedelta(days=30)).isoformat(), "notiz": "Ratenzahlung vereinbart"},
    )
    a.kontakt.refresh_from_db()
    assert a.kontakt.notiz == "Ratenzahlung vereinbart"
    assert not Mahnvorschlag.objects.exists()
    assert vorschlagslauf(firma).neu == []
    html = client_inhaber.get(reverse("ledger:kunde", args=[a.kontakt.pk])).content.decode()
    assert "Pausiert bis" in html
    assert b.pk


def test_versendete_vorschlaege_bleiben_beim_pausieren(client_inhaber, firma, posten, heute):
    from tests.dunning.conftest import versendet

    beleg = posten(tage=40)
    v = versendet(beleg, 0, tage_her=30)
    client_inhaber.post(
        reverse("ledger:beleg_pause", args=[beleg.pk]), {"mahnpause_bis": (HEUTE + timedelta(days=5)).isoformat()}
    )
    assert Mahnvorschlag.objects.filter(pk=v.pk, status="versendet").exists()


def test_mitarbeiter_darf_nicht_pausieren(client_mitarbeiter, firma, posten, heute):
    beleg = posten(tage=10)
    assert (
        client_mitarbeiter.post(
            reverse("ledger:beleg_pause", args=[beleg.pk]), {"mahnpause_bis": "2026-12-01"}
        ).status_code
        == 403
    )
    assert (
        client_mitarbeiter.post(
            reverse("ledger:kontakt_pause", args=[beleg.kontakt.pk]), {"mahnpause_bis": "2026-12-01"}
        ).status_code
        == 403
    )
    html = client_mitarbeiter.get(reverse("ledger:beleg", args=[beleg.pk])).content.decode()
    assert "Mahnpause für diesen Beleg" not in html


def test_belegansicht_und_verzugshinweis(client_inhaber, firma, posten, heute):
    beleg = posten(tage=40, kundentyp="privat")
    html = client_inhaber.get(reverse("ledger:beleg", args=[beleg.pk])).content.decode()
    assert beleg.nummer in html
    client_inhaber.post(reverse("ledger:beleg_verzugshinweis", args=[beleg.pk]), {"verzugshinweis": "ja"})
    beleg.refresh_from_db()
    assert beleg.verzugshinweis_enthalten is True
    # Mit Hinweis: Verzug ab Fälligkeit + 30 auch ohne Erinnerung (wirkt in Stufe 1, nicht in Stufe 0)
    from dunning.recht import verzugsbeginn
    from dunning.services import mahnplan_fuer
    from dunning.vorschlaege import forderung

    assert verzugsbeginn(forderung(beleg, mahnplan_fuer(firma))) == beleg.faellig_am + timedelta(days=30)
    client_inhaber.post(reverse("ledger:beleg_verzugshinweis", args=[beleg.pk]), {"verzugshinweis": ""})
    beleg.refresh_from_db()
    assert beleg.verzugshinweis_enthalten is None
    assert Protokolleintrag.objects.filter(ereignis="beleg.verzugshinweis_gesetzt").count() == 2


def test_postenliste_zeigt_pause(client_inhaber, firma, posten, heute):
    posten(tage=10, mahnpause_bis=HEUTE + timedelta(days=3))
    assert "pausiert bis" in client_inhaber.get(reverse("ledger:posten")).content.decode()
