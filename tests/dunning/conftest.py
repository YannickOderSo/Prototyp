from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from dunning.models import Mahnvorschlag
from ledger.models import Beleg, Kontakt

HEUTE = date(2026, 11, 5)
BERLIN = ZoneInfo("Europe/Berlin")


@pytest.fixture
def heute():
    import time_machine

    with time_machine.travel(datetime(2026, 11, 5, 5, 0, tzinfo=BERLIN), tick=False):
        yield HEUTE


@pytest.fixture
def posten(firma):
    """Fabrik: legt Kontakt und Beleg an. `tage` = Tage seit Fälligkeit."""
    zaehler = {"n": 0}

    def anlegen(
        tage=10, kundentyp="unternehmer", email="kunde@example.org", offen="1190.00", brutto=None, kontakt=None, **beleg
    ):
        zaehler["n"] += 1
        n = zaehler["n"]
        if kontakt is None and kundentyp is not None:
            kontakt = Kontakt.objects.create(
                firma=firma, extern_id=f"k{n}", name=f"Kunde {n}", email=email, kundentyp=kundentyp
            )
        faellig = beleg.pop("faellig_am", HEUTE - timedelta(days=tage))
        return Beleg.objects.create(
            firma=firma,
            extern_id=f"inv-{n}",
            nummer=f"RE{1000 + n}",
            kontakt=kontakt,
            kontakt_name=kontakt.name if kontakt else "Sammelkunde",
            belegdatum=beleg.pop("belegdatum", (faellig or HEUTE) - timedelta(days=14)),
            faellig_am=faellig,
            offen=Decimal(offen),
            brutto=Decimal(brutto or offen),
            status=beleg.pop("status", "ueberfaellig"),
            **beleg,
        )

    return anlegen


def versendet(beleg, stufe, tage_her, pauschale="0.00"):
    return Mahnvorschlag.objects.create(
        firma=beleg.firma,
        beleg=beleg,
        stufe=stufe,
        status=Mahnvorschlag.Status.VERSENDET,
        versendet_am=datetime.combine(HEUTE - timedelta(days=tage_her), datetime.min.time(), tzinfo=BERLIN).replace(
            hour=9
        ),
        offen_betrag=beleg.offen,
        pauschale=Decimal(pauschale),
        gesamt=beleg.offen,
    )
