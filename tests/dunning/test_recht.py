"""M2-02: Tabellen-Tests für jede Zeile aus vault/02-Architektur/Mahnlogik-und-Recht.md (D4, D5).

Zinskonvention: Verzugsbeginn ist der Tag aus der Tabelle; Zinsen laufen ab dem Folgetag bis einschließlich
Stichtag. Stichtag in den Beispielen ist der Berechnungstag der Mahnung.
"""

from datetime import date
from decimal import Decimal

import pytest

from dunning.recht import (
    PAUSCHALE,
    BasiszinsEintrag,
    Forderung,
    basiszins_am,
    berechne,
    naechster_wechsel,
    pauschale,
    verzug_besteht,
    verzugsbeginn,
    verzugszinsen,
    zinstext,
)

D = Decimal
TABELLE = [
    BasiszinsEintrag(date(2025, 1, 1), D("2.27")),
    BasiszinsEintrag(date(2025, 7, 1), D("1.27")),
    BasiszinsEintrag(date(2026, 1, 1), D("1.27")),
    BasiszinsEintrag(date(2026, 7, 1), D("1.52")),
]
BELEG = date(2026, 10, 1)
FAELLIG = date(2026, 10, 15)


# ------------------------------------------------------------------ Verzugsbeginn (§ 286 BGB)
@pytest.mark.parametrize(
    ("fall", "forderung", "stufe0_versendet", "erwartet"),
    [
        # Zeile 1: Unternehmer, Rechnung zugegangen → Fälligkeit + 30 (Zugang = Belegdatum + 3)
        ("Unternehmer, Zugang vor Fälligkeit", Forderung(BELEG, FAELLIG, "unternehmer"), None, date(2026, 11, 14)),
        (
            "Unternehmer, sofort fällig: 30 Tage ab Zugang",
            Forderung(BELEG, BELEG, "unternehmer"),
            None,
            date(2026, 11, 3),
        ),
        ("Unternehmer ohne Belegdatum", Forderung(None, FAELLIG, "unternehmer"), None, date(2026, 11, 14)),
        # Zeile 2: Privatkunde mit Verzugshinweis → Fälligkeit + 30
        ("Privat mit Hinweis", Forderung(BELEG, FAELLIG, "privat", verzugshinweis=True), None, date(2026, 11, 14)),
        (
            "Privat mit Hinweis, frühe Erinnerung zählt nicht",
            Forderung(BELEG, FAELLIG, "privat", True),
            date(2026, 10, 22),
            date(2026, 11, 14),
        ),
        # Zeile 3: Privatkunde ohne Hinweis → Zugang der ersten Mahnung nach Fälligkeit (Versand Stufe 0 + 1 Tag)
        ("Privat ohne Hinweis, keine Erinnerung", Forderung(BELEG, FAELLIG, "privat"), None, None),
        (
            "Privat ohne Hinweis, Erinnerung versendet",
            Forderung(BELEG, FAELLIG, "privat"),
            date(2026, 10, 22),
            date(2026, 10, 23),
        ),
        (
            "Privat ohne Hinweis, Schreiben am Fälligkeitstag ist keine Mahnung nach Fälligkeit",
            Forderung(BELEG, FAELLIG, "privat"),
            FAELLIG,
            None,
        ),
        # Zeile 4: Unternehmer, Stufe 0 vor Ablauf der 30 Tage → früheres aus Zugang Stufe 0 + 1 Tag und Fälligkeit + 30
        (
            "Unternehmer, Erinnerung vor Ablauf der 30 Tage",
            Forderung(BELEG, FAELLIG, "unternehmer"),
            date(2026, 10, 22),
            date(2026, 10, 24),
        ),
        (
            "Unternehmer, Erinnerung nach Ablauf der 30 Tage",
            Forderung(BELEG, FAELLIG, "unternehmer"),
            date(2026, 11, 20),
            date(2026, 11, 14),
        ),
        # Zeile 5: Fälligkeit fehlt → kein Verzug berechenbar
        ("Fälligkeit fehlt, Unternehmer", Forderung(BELEG, None, "unternehmer"), date(2026, 10, 22), None),
        ("Fälligkeit fehlt, Privat", Forderung(BELEG, None, "privat"), date(2026, 10, 22), None),
        # ohne Kundentyp nie Verzug (D3)
        ("Kundentyp unbekannt", Forderung(BELEG, FAELLIG, "unbekannt"), date(2026, 10, 22), None),
    ],
)
def test_verzugsbeginn(fall, forderung, stufe0_versendet, erwartet):
    assert verzugsbeginn(forderung, stufe0_versendet) == erwartet, fall


def test_verzug_besteht_erst_nach_dem_tag_des_verzugsbeginns():
    assert not verzug_besteht(None, date(2026, 11, 20))
    assert not verzug_besteht(date(2026, 11, 14), date(2026, 11, 14))
    assert verzug_besteht(date(2026, 11, 14), date(2026, 11, 15))


# ------------------------------------------------------------------ Basiszins
@pytest.mark.parametrize(
    ("tag", "erwartet"),
    [
        (date(2025, 1, 1), D("2.27")),
        (date(2025, 6, 30), D("2.27")),
        (date(2025, 7, 1), D("1.27")),
        (date(2026, 6, 30), D("1.27")),
        (date(2026, 7, 1), D("1.52")),
        (date(2026, 12, 31), D("1.52")),
        (date(2027, 1, 1), None),  # Folgewert nicht gepflegt
        (date(2024, 12, 31), None),  # vor der Tabelle
    ],
)
def test_basiszins_am(tag, erwartet):
    assert basiszins_am(tag, TABELLE) == erwartet


def test_naechster_wechsel():
    assert naechster_wechsel(date(2026, 1, 1)) == date(2026, 7, 1)
    assert naechster_wechsel(date(2026, 6, 30)) == date(2026, 7, 1)
    assert naechster_wechsel(date(2026, 7, 1)) == date(2027, 1, 1)


# ------------------------------------------------------------------ Verzugszinsen (§ 288 BGB)
@pytest.mark.parametrize(
    ("fall", "offen", "beginn", "stichtag", "kundentyp", "tabelle", "erwartet", "abschnitte"),
    [
        # 30 Zinstage (2.8.–31.8.), 1,52 + 9 = 10,52 %: 1000 × 0,1052 × 30/365 = 8,6466 → 8,65
        (
            "Unternehmer + 9 Prozentpunkte",
            D("1000.00"),
            date(2026, 8, 1),
            date(2026, 8, 31),
            "unternehmer",
            TABELLE,
            D("8.65"),
            1,
        ),
        # 1,52 + 5 = 6,52 %: 1000 × 0,0652 × 30/365 = 5,3589 → 5,36
        (
            "Privat + 5 Prozentpunkte",
            D("1000.00"),
            date(2026, 8, 1),
            date(2026, 8, 31),
            "privat",
            TABELLE,
            D("5.36"),
            1,
        ),
        # Wechsel zum 1.7.: 15 Tage zu 10,27 % (4,22) + 15 Tage zu 10,52 % (4,32)
        (
            "Basiszinswechsel 1.7.",
            D("1000.00"),
            date(2026, 6, 15),
            date(2026, 7, 15),
            "unternehmer",
            TABELLE,
            D("8.54"),
            2,
        ),
        # Wechsel zum 1.1.: 11 Tage 2025 zu 10,27 % (3,10) + 10 Tage 2026 zu 10,27 % (2,81)
        (
            "Basiszinswechsel 1.1.",
            D("1000.00"),
            date(2025, 12, 20),
            date(2026, 1, 10),
            "unternehmer",
            TABELLE,
            D("5.91"),
            2,
        ),
        # Teilzahlung: Zinsen auf den offenen Betrag aus Lexware (500 statt 1000)
        ("Teilzahlung", D("500.00"), date(2026, 8, 1), date(2026, 8, 31), "unternehmer", TABELLE, D("4.32"), 1),
        # Schaltjahr 2028: Divisor 366; 30 Tage zu 11 %: 1000 × 0,11 × 30/366 = 9,0164 → 9,02
        (
            "Schaltjahr",
            D("1000.00"),
            date(2028, 2, 1),
            date(2028, 3, 2),
            "unternehmer",
            [BasiszinsEintrag(date(2028, 1, 1), D("2.00"))],
            D("9.02"),
            1,
        ),
        # kein Zinstag am Tag des Verzugsbeginns
        (
            "Stichtag = Verzugsbeginn",
            D("1000.00"),
            date(2026, 8, 1),
            date(2026, 8, 1),
            "unternehmer",
            TABELLE,
            D("0.00"),
            0,
        ),
        ("kein Verzug", D("1000.00"), None, date(2026, 8, 31), "unternehmer", TABELLE, D("0.00"), 0),
        (
            "unbekannter Kundentyp",
            D("1000.00"),
            date(2026, 8, 1),
            date(2026, 8, 31),
            "unbekannt",
            TABELLE,
            D("0.00"),
            0,
        ),
        ("nichts offen", D("0.00"), date(2026, 8, 1), date(2026, 8, 31), "unternehmer", TABELLE, D("0.00"), 0),
    ],
)
def test_verzugszinsen(fall, offen, beginn, stichtag, kundentyp, tabelle, erwartet, abschnitte):
    ergebnis = verzugszinsen(offen, beginn, stichtag, kundentyp, tabelle)
    assert ergebnis.betrag == erwartet, fall
    assert len(ergebnis.abschnitte) == abschnitte, fall
    assert isinstance(ergebnis.betrag, Decimal)


def test_zinsabschnitte_im_detail():
    ergebnis = verzugszinsen(D("1000.00"), date(2026, 6, 15), date(2026, 7, 15), "unternehmer", TABELLE)
    juni, juli = ergebnis.abschnitte
    assert (juni.von, juni.bis, juni.tage, juni.zinssatz, juni.jahrestage, juni.betrag) == (
        date(2026, 6, 16),
        date(2026, 6, 30),
        15,
        D("10.27"),
        365,
        D("4.22"),
    )
    assert (juli.von, juli.bis, juli.tage, juli.zinssatz, juli.betrag) == (
        date(2026, 7, 1),
        date(2026, 7, 15),
        15,
        D("10.52"),
        D("4.32"),
    )


def test_fehlender_basiszins_keine_zinsen():
    ergebnis = verzugszinsen(D("1000.00"), date(2026, 12, 1), date(2027, 1, 10), "unternehmer", TABELLE)
    assert ergebnis.basiszins_fehlt
    assert ergebnis.betrag == D("0.00")
    assert verzugszinsen(D("1000.00"), date(2024, 11, 1), date(2024, 12, 1), "unternehmer", TABELLE).basiszins_fehlt


def test_zinsen_unter_einem_euro_werden_nicht_ausgewiesen():
    ergebnis = verzugszinsen(D("10.00"), date(2026, 8, 1), date(2026, 8, 31), "unternehmer", TABELLE)
    assert ergebnis.betrag == D("0.00")
    assert ergebnis.unter_mindestbetrag
    assert ergebnis.abschnitte[0].betrag == D("0.09")


def test_kaufmaennische_rundung_half_up():
    # 18,25 × 10 % × 1/365 = 0,005 → 0,01 (ROUND_HALF_UP, nicht Banker's Rounding)
    tabelle = [BasiszinsEintrag(date(2026, 7, 1), D("1.00"))]
    ergebnis = verzugszinsen(D("18.25"), date(2026, 8, 1), date(2026, 8, 2), "unternehmer", tabelle)
    assert ergebnis.abschnitte[0].betrag == D("0.01")


# ------------------------------------------------------------------ Pauschale (§ 288 Abs. 5 BGB)
@pytest.mark.parametrize(
    ("fall", "kundentyp", "beginn", "stichtag", "bereits", "erwartet"),
    [
        ("Unternehmer im Verzug", "unternehmer", date(2026, 11, 14), date(2026, 11, 15), False, PAUSCHALE),
        (
            "Unternehmer, Verzug noch nicht eingetreten",
            "unternehmer",
            date(2026, 11, 14),
            date(2026, 11, 14),
            False,
            D("0.00"),
        ),
        ("Unternehmer ohne Verzugsbeginn", "unternehmer", None, date(2026, 11, 15), False, D("0.00")),
        ("einmal je Forderung", "unternehmer", date(2026, 11, 14), date(2026, 12, 15), True, D("0.00")),
        ("Privatkunde nie", "privat", date(2026, 10, 23), date(2026, 12, 15), False, D("0.00")),
        ("ohne Kundentyp nie", "unbekannt", date(2026, 10, 23), date(2026, 12, 15), False, D("0.00")),
    ],
)
def test_pauschale(fall, kundentyp, beginn, stichtag, bereits, erwartet):
    assert pauschale(kundentyp, beginn, stichtag, bereits) == erwartet, fall


# ------------------------------------------------------------------ Gesamtberechnung je Stufe
def test_stufe_0_nie_zinsen_oder_pauschale():
    b = berechne(
        0, Forderung(date(2026, 5, 18), date(2026, 6, 1), "unternehmer"), D("1000.00"), date(2026, 12, 1), TABELLE
    )
    assert (b.zinsen, b.pauschale, b.gesamt) == (D("0.00"), D("0.00"), D("1000.00"))
    assert b.verzugsbeginn == date(2026, 7, 1)


def test_stufe_1_unternehmer_mit_zinsen_und_pauschale():
    forderung = Forderung(BELEG, FAELLIG, "unternehmer")
    b = berechne(1, forderung, D("1190.00"), date(2026, 11, 5), TABELLE, erinnerung_versendet_am=date(2026, 10, 22))
    # Verzug ab 24.10.: 12 Zinstage (25.10.–5.11.), 1190 × 10,52 % × 12/365 = 4,1158 → 4,12
    assert b.verzugsbeginn == date(2026, 10, 24)
    assert b.zinsen == D("4.12")
    assert b.pauschale == D("40.00")
    assert b.gesamt == D("1234.12")
    assert "1.190,00 € × 10,52 % p. a." in zinstext(b.zinsergebnis)
    assert "(25.10.2026–05.11.2026) = 4,12 €" in zinstext(b.zinsergebnis)


def test_stufe_1_privat_ohne_pauschale():
    b = berechne(1, Forderung(BELEG, FAELLIG, "privat"), D("1000.00"), date(2026, 11, 22), TABELLE, date(2026, 10, 22))
    # Verzug ab 23.10.: 30 Zinstage zu 6,52 % = 5,36
    assert b.zinsen == D("5.36")
    assert b.pauschale == D("0.00")


def test_schalter_und_hinweise():
    forderung = Forderung(BELEG, FAELLIG, "unternehmer")
    aus = berechne(1, forderung, D("1000.00"), date(2026, 12, 1), TABELLE, zinsen_aktiv=False, pauschale_aktiv=False)
    assert (aus.zinsen, aus.pauschale) == (D("0.00"), D("0.00"))
    bereits = berechne(2, forderung, D("1000.00"), date(2026, 12, 20), TABELLE, pauschale_bereits_geltend_gemacht=True)
    assert bereits.pauschale == D("0.00")
    assert any("bereits" in h for h in bereits.hinweise)
    ohne_faelligkeit = berechne(1, Forderung(BELEG, None, "unternehmer"), D("1000.00"), date(2026, 12, 1), TABELLE)
    assert ohne_faelligkeit.zinsen == D("0.00") and ohne_faelligkeit.pauschale == D("0.00")
    assert any("Fälligkeit fehlt" in h for h in ohne_faelligkeit.hinweise)
    veraltet = berechne(1, forderung, D("1000.00"), date(2027, 1, 20), TABELLE)
    assert veraltet.zinsen == D("0.00")
    assert veraltet.pauschale == D("40.00")
    assert any("Basiszins" in h for h in veraltet.hinweise)
    frueh = berechne(1, Forderung(BELEG, FAELLIG, "privat"), D("1000.00"), date(2026, 11, 5), TABELLE)
    assert any("noch nicht eingetreten" in h for h in frueh.hinweise)


def test_zinstext_leer_ohne_zinsen():
    assert zinstext(verzugszinsen(D("1"), None, date(2026, 1, 1), "privat", TABELLE)) == ""
