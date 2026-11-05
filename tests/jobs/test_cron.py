from datetime import datetime

import pytest

from jobs.cron import Cron


@pytest.mark.parametrize(
    ("ausdruck", "nach", "erwartet"),
    [
        ("0 5 * * *", datetime(2026, 11, 5, 4, 59), datetime(2026, 11, 5, 5, 0)),
        ("0 5 * * *", datetime(2026, 11, 5, 5, 0), datetime(2026, 11, 6, 5, 0)),
        ("0 7 * * 1", datetime(2026, 11, 5, 8, 0), datetime(2026, 11, 9, 7, 0)),  # nächster Montag
        ("*/15 * * * *", datetime(2026, 11, 5, 10, 1), datetime(2026, 11, 5, 10, 15)),
        ("0 2 * * *", datetime(2026, 12, 31, 23, 30), datetime(2027, 1, 1, 2, 0)),
        ("0 0 29 2 *", datetime(2026, 3, 1), datetime(2028, 2, 29, 0, 0)),  # Schaltjahr
        ("30 3 1,15 * *", datetime(2026, 11, 2), datetime(2026, 11, 15, 3, 30)),
        ("0 9-17/4 * * *", datetime(2026, 11, 5, 9, 30), datetime(2026, 11, 5, 13, 0)),
        ("0 7 * * 7", datetime(2026, 11, 5), datetime(2026, 11, 8, 7, 0)),  # 7 = Sonntag
    ],
)
def test_naechster_termin(ausdruck, nach, erwartet):
    assert Cron(ausdruck).naechster(nach) == erwartet


@pytest.mark.parametrize("ausdruck", ["* * * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "5-1 * * * *"])
def test_ungueltige_ausdruecke(ausdruck):
    with pytest.raises(ValueError):
        Cron(ausdruck)


def test_passt():
    cron = Cron("0 7 * * 1")
    assert cron.passt(datetime(2026, 11, 9, 7, 0))
    assert not cron.passt(datetime(2026, 11, 10, 7, 0))
