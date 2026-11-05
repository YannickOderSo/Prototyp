"""M7-03/04: Zustand je Angebot und Kennzahlen (I2, I3)."""

from datetime import date, timedelta

import pytest

from ledger import angebote
from ledger.models import Beleg

pytestmark = pytest.mark.django_db
HEUTE = date(2026, 11, 5)


def _angebot(firma, nr, status="offen", tage_alt=10, gueltig=None, brutto=1000):
    return Beleg.objects.create(
        firma=firma,
        extern_id=f"q-{nr}",
        art="angebot",
        nummer=f"AN-{nr}",
        status=status,
        brutto=brutto,
        belegdatum=HEUTE - timedelta(days=tage_alt),
        gueltig_bis=HEUTE + timedelta(days=gueltig) if gueltig is not None else None,
    )


def test_zustand_und_sortierung(firma):
    _angebot(firma, 1, gueltig=20)
    _angebot(firma, 2, gueltig=2)
    _angebot(firma, 3, gueltig=-1)
    _angebot(firma, 4)
    _angebot(firma, 5, status="angenommen")
    reihenfolge = [(a.beleg.nummer, a.zustand) for a in angebote.offene(firma, HEUTE, abgelaufene=True)]
    assert reihenfolge == [("AN-2", "laeuft_ab"), ("AN-1", "offen"), ("AN-4", "offen"), ("AN-3", "abgelaufen")]
    assert [a.beleg.nummer for a in angebote.offene(firma, HEUTE)] == ["AN-2", "AN-1", "AN-4"]
    assert angebote.bald_ablaufend(firma, HEUTE) == 1


def test_kennzahlen_im_zeitraum(firma, andere_firma):
    _angebot(firma, 1, status="angenommen", brutto=5000)
    _angebot(firma, 2, status="abgelehnt")
    _angebot(firma, 3, gueltig=-3)
    _angebot(firma, 4, gueltig=10, brutto=2000)
    _angebot(firma, 5, status="angenommen", tage_alt=200)  # außerhalb
    _angebot(firma, 6, status="storniert")  # zählt nicht
    _angebot(andere_firma, 7, status="angenommen")  # andere Firma
    k = angebote.kennzahlen(firma, HEUTE - timedelta(days=90), HEUTE, HEUTE)
    assert (k.verschickt, k.angenommen, k.abgelehnt, k.abgelaufen, k.offen) == (4, 1, 1, 1, 1)
    assert k.angenommen_volumen == 5000 and k.offen_volumen == 2000 and k.volumen == 9000
    assert k.quote == 33  # 1 von 3 entschiedenen
    assert angebote.kennzahlen(firma, HEUTE, HEUTE, HEUTE).quote is None
