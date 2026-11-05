"""M3-10: KI-Testfälle (mindestens 12) laufen im Standardlauf gegen das gemockte Modell; das Kommando ki_testfaelle
nutzt dieselbe Bewertung gegen das echte Modell."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from capture import ki_testfaelle
from capture.ki_testfaelle import abnahme, ausfuehren, faelle_laden
from tests.ki_fake import antwort

pytestmark = pytest.mark.django_db
FAELLE = faelle_laden()


def test_mindestens_zwoelf_faelle_mit_pflichtthemen():
    namen = " ".join(f.name for f in FAELLE)
    assert len(FAELLE) >= 12
    for thema in (
        "einfache_rechnung",
        "angebot",
        "unbekannter_kunde",
        "artikel_fehlt",
        "dialekt",
        "zahl_als_wort",
        "versteckte_anweisung",
        "keine_belegabsicht",
        "mehrere_kunden",
        "foto_stundenzettel",
        "csv_zeiterfassung",
        "mehraufwand",
    ):
        assert thema in namen, thema
    assert sum(f.sicherheit for f in FAELLE) >= 3


@pytest.mark.parametrize("fall", FAELLE, ids=[f.name for f in FAELLE])
def test_fall_mit_beispielantwort(fall, ki, settings, tmp_path):
    settings.DATEIABLAGE = tmp_path
    client = ki(antwort(fall.beispielantwort))
    ergebnis = ausfuehren(fall)
    assert ergebnis.bestanden, (ergebnis.fehler, ergebnis.abweichungen)
    aufruf = client.messages.aufrufe[0]
    if fall.bilder:
        assert aufruf["messages"][0]["content"][0]["type"] == "image"
    if fall.csv:
        assert "bereits addiert" in json.dumps(aufruf["messages"], ensure_ascii=False)


def test_temporaere_daten_werden_zurueckgerollt(ki, settings, tmp_path):
    from accounts.models import Firma

    settings.DATEIABLAGE = tmp_path
    ki(antwort(FAELLE[0].beispielantwort))
    ausfuehren(FAELLE[0])
    assert not Firma.objects.filter(name__startswith="KI-Testfälle").exists()


def test_bewertung_erkennt_falsche_antworten(ki, settings, tmp_path):
    settings.DATEIABLAGE = tmp_path
    fall = next(f for f in FAELLE if "versteckte_anweisung" in f.name)
    falsch = {**fall.beispielantwort, "offene_fragen": [], "positionen": []}
    ki(antwort(falsch))
    ergebnis = ausfuehren(fall)
    assert not ergebnis.bestanden
    assert any("Keine offene Frage" in a for a in ergebnis.abweichungen)


def test_abnahme_regel():
    class F:
        def __init__(self, sicherheit):
            self.sicherheit = sicherheit

    def erg(ok, sicherheit=False):
        return ki_testfaelle.Ergebnis(F(sicherheit), [] if ok else ["x"])

    assert abnahme([erg(True)] * 11 + [erg(False)])[0]
    assert not abnahme([erg(True)] * 10 + [erg(False)] * 2)[0]
    assert not abnahme([erg(True)] * 11 + [erg(False, sicherheit=True)])[0]


def test_kommando_mit_gemocktem_modell(ki, capsys):
    fall = FAELLE[0]
    ki(antwort(fall.beispielantwort))
    call_command("ki_testfaelle", "--nur", fall.name)
    ausgabe = capsys.readouterr().out
    assert f"OK   {fall.name}" in ausgabe
    assert "1/1 bestanden" in ausgabe


def test_kommando_meldet_nicht_bestanden(ki):
    ki(antwort({**FAELLE[0].beispielantwort, "kunde": "Falsch"}))
    with pytest.raises(CommandError, match="Abnahme nicht erreicht"):
        call_command("ki_testfaelle", "--nur", FAELLE[0].name)
