"""M1-09: Kennzahlen, Altersstruktur, Zahlungsdauer, Prognose als nachvollziehbare Unit-Tests (C1, C3, C4, C6)."""

from datetime import date, timedelta
from decimal import Decimal

from ledger.auswertung import (
    Posten,
    Zahlung,
    erwarteter_eingang,
    kennzahlen,
    prognose,
    verzug,
    verzug_je_monat,
    zahlungsdauer,
)

HEUTE = date(2026, 11, 5)
D = Decimal


def tage_her(n):
    return HEUTE - timedelta(days=n)


def test_kennzahlen_und_altersstruktur_mit_bekannten_summen():
    posten = [
        Posten(D("100.00"), HEUTE + timedelta(days=3)),  # nicht fällig
        Posten(D("200.00"), HEUTE),  # heute fällig: noch nicht überfällig
        Posten(D("300.00"), tage_her(1)),  # 1–30
        Posten(D("400.00"), tage_her(30)),  # 1–30
        Posten(D("500.00"), tage_her(31)),  # 31–60
        Posten(D("600.00"), tage_her(60)),  # 31–60
        Posten(D("700.00"), tage_her(61)),  # 61–90
        Posten(D("800.00"), tage_her(91)),  # über 90
        Posten(D("50.50"), None, belegdatum=tage_her(10)),  # ohne Fälligkeit: Belegdatum zählt → 1–30
        Posten(D("0.00"), tage_her(100)),  # bezahlt: zählt nicht
    ]
    k = kennzahlen(posten, HEUTE)
    assert k.summe_offen == D("3650.50")
    assert k.anzahl_offen == 9
    assert k.summe_nicht_faellig == D("300.00")
    assert k.summe_ueberfaellig == D("3350.50")
    assert k.anzahl_ueberfaellig == 7
    assert [(kl.summe, kl.anzahl) for kl in k.klassen] == [
        (D("750.50"), 3),
        (D("1100.00"), 2),
        (D("700.00"), 1),
        (D("800.00"), 1),
    ]
    assert sum(kl.anteil for kl in k.klassen) in (99, 100, 101)


def test_kennzahlen_leer():
    k = kennzahlen([], HEUTE)
    assert k.summe_offen == D("0.00")
    assert all(kl.anteil == 0 for kl in k.klassen)


def test_zahlungsdauer_und_verzug_nur_letzte_12_monate():
    zahlungen = [
        Zahlung(belegdatum=date(2026, 9, 1), faellig_am=date(2026, 9, 15), bezahlt_am=date(2026, 9, 25)),  # 24 / 10
        Zahlung(belegdatum=date(2026, 10, 1), faellig_am=date(2026, 10, 15), bezahlt_am=date(2026, 10, 13)),  # 12 / -2
        Zahlung(belegdatum=date(2025, 1, 1), faellig_am=date(2025, 1, 15), bezahlt_am=date(2025, 3, 1)),  # zu alt
    ]
    assert zahlungsdauer(zahlungen, HEUTE) == D("18.0")
    assert verzug(zahlungen, HEUTE) == D("4.0")
    assert zahlungsdauer([], HEUTE) is None


def test_prognose_nachvollziehbar():
    verzug_je_kontakt = {1: D("10.0"), 2: D("-5.0"), 3: None}
    posten = [
        Posten(D("100.00"), HEUTE + timedelta(days=2), kontakt_id=3),  # Woche 1 (Tag 2)
        Posten(D("200.00"), HEUTE, kontakt_id=1),  # +10 Tage → Woche 2
        Posten(D("300.00"), HEUTE + timedelta(days=14), kontakt_id=2),  # früher Zahler: nie vor Fälligkeit → Woche 3
        Posten(D("400.00"), HEUTE + timedelta(days=27), kontakt_id=3),  # Woche 4 (Tag 27)
        Posten(D("500.00"), HEUTE + timedelta(days=28), kontakt_id=3),  # außerhalb (Tag 28)
        Posten(D("600.00"), tage_her(20), kontakt_id=1),  # erwartet vor 10 Tagen → unsicher
        Posten(D("700.00"), None, kontakt_id=None),  # weder Fälligkeit noch Belegdatum → unsicher
    ]
    p = prognose(posten, verzug_je_kontakt, HEUTE)
    assert [w.summe for w in p.wochen] == [D("100.00"), D("200.00"), D("300.00"), D("400.00")]
    assert p.wochen[0].beginn == HEUTE
    assert p.wochen[3].ende == HEUTE + timedelta(days=27)
    assert p.summe == D("1000.00")
    assert p.unsicher == D("1300.00")
    assert p.anzahl_unsicher == 2


def test_erwarteter_eingang_rundet_kaufmaennisch():
    assert erwarteter_eingang(Posten(D("1"), HEUTE), D("2.5")) == HEUTE + timedelta(days=3)
    assert erwarteter_eingang(Posten(D("1"), HEUTE), D("2.4")) == HEUTE + timedelta(days=2)


def test_verzug_je_monat_sechs_monate():
    zahlungen = [
        Zahlung(None, date(2026, 11, 1), date(2026, 11, 4)),  # 3 Tage
        Zahlung(None, date(2026, 10, 1), date(2026, 10, 11)),  # 10
        Zahlung(None, date(2026, 10, 1), date(2026, 10, 21)),  # 20
        Zahlung(None, date(2026, 3, 1), date(2026, 4, 1)),  # außerhalb
        Zahlung(None, None, date(2026, 9, 1)),  # ohne Fälligkeit
    ]
    monate = verzug_je_monat(zahlungen, HEUTE)
    assert [m.monat for m in monate] == [date(2026, m, 1) for m in (6, 7, 8, 9, 10, 11)]
    werte = {m.monat.month: (m.tage, m.anzahl) for m in monate}
    assert werte[11] == (D("3.0"), 1)
    assert werte[10] == (D("15.0"), 2)
    assert werte[9] == (None, 0)
    assert max(m.anteil for m in monate) == 100
