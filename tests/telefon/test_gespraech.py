"""M8-02/03: Gesprächsführung des KI-Telefonassistenten, Rückruf-Notizen, Grenzen und Ausfallbetrieb (J1–J5, J8)."""

from datetime import timedelta
from itertools import pairwise

import anthropic
import httpx
import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from audit.models import Protokolleintrag
from jobs.models import Job
from ledger.models import Kontakt
from telefon import gespraech as fuehrung
from telefon.models import Gespraech, Rueckruf, Telefonassistent
from tests.conftest import alle_jobs_ausfuehren
from tests.ki_fake import antwort

pytestmark = pytest.mark.django_db


def _ki_antwort(text, beenden=False, **erfasst):
    felder = {"name": "", "anliegen": "", "rueckrufnummer": "", "beste_zeit": "", "dringlichkeit": ""}
    felder.update(erfasst)
    return antwort({"antwort": text, "erfasst": felder, "beenden": beenden}, eingabe=900, ausgabe=80)


def test_ansage_mit_pflichthinweis(firma):
    text = fuehrung.ansage(firma)
    assert text.startswith(f"Guten Tag, Sie sind verbunden mit {firma.name}.")
    assert "digitaler Assistent" in text and "in Text umgewandelt und gespeichert" in text and "112" in text
    Telefonassistent.objects.create(firma=firma, begruessung="Moin, hier ist die Malerei Muster!")
    text = fuehrung.ansage(firma)
    assert text.startswith("Moin, hier ist die Malerei Muster!") and fuehrung.PFLICHTHINWEIS in text


def test_gespraech_ergibt_rueckruf_und_benachrichtigung(firma, inhaber, ki, worker):
    Kontakt.objects.create(firma=firma, extern_id="k1", name="Familie Weber")
    client = ki(
        _ki_antwort(
            "Danke, Frau Weber. Passt die Nummer 0151 2345678 für den Rückruf?",
            name="Familie Weber",
            anliegen="Wasserfleck an der Küchendecke",
            dringlichkeit="dringend",
        ),
        _ki_antwort("Alles klar, ich habe es notiert.", beenden=True, rueckrufnummer="0151 2345678"),
    )
    g, start = fuehrung.starten(firma, anrufer_nummer="+49 151 2345678")
    assert start == fuehrung.ansage(firma) and g.anrufer_nummer == "+491512345678"
    erste = fuehrung.antworten(
        g, "Hallo, hier Weber, bei uns ist ein Wasserfleck an der Küchendecke, ziemlich dringend."
    )
    assert not erste.beendet and "0151" in erste.text
    zweite = fuehrung.antworten(g, "Ja, die passt.")
    assert zweite.beendet and zweite.text.endswith(fuehrung.ABSCHIED)
    r = Rueckruf.objects.get(gespraech=g)
    assert (r.name, r.anliegen, r.rueckrufnummer, r.dringlichkeit) == (
        "Familie Weber",
        "Wasserfleck an der Küchendecke",
        "01512345678",
        "dringend",
    )
    assert r.kontakt.name == "Familie Weber" and not r.test
    g.refresh_from_db()
    assert g.status == "beendet" and [e["rolle"] for e in g.verlauf] == [
        "assistent",
        "anrufer",
        "assistent",
        "anrufer",
        "assistent",
    ]
    # Nachrichtenfolge an die KI: beginnt mit dem Anrufer, Rollen wechseln sich ab
    rollen = [n["role"] for n in client.messages.aufrufe[1]["messages"]]
    assert rollen[0] == "user" and rollen[-1] == "user" and all(a != b for a, b in pairwise(rollen))
    assert (
        "keine Preise" not in client.messages.aufrufe[0]["system"]
        and "Nenne nie Preise" in client.messages.aufrufe[0]["system"]
    )
    # Benachrichtigung: nur Name, Dringlichkeit und Link, nicht das Anliegen
    assert Job.objects.filter(typ="telefon.benachrichtigen").count() == 1
    alle_jobs_ausfuehren(worker)
    nachricht = mail.outbox[0]
    assert nachricht.subject == "Dringender Rückruf: Familie Weber" and inhaber.email in nachricht.to
    assert reverse("telefon:rueckruf", args=[r.pk]) in nachricht.body and "Wasserfleck" not in nachricht.body
    assert Protokolleintrag.objects.filter(ereignis="telefon.rueckruf_angelegt").exists()


@pytest.mark.parametrize(
    "ki_text",
    [
        "Das kostet ungefähr 250 Euro.",
        "Ein Fliesenwechsel liegt bei 80 € pro Quadratmeter.",
        "Wir kommen morgen um 9 Uhr vorbei.",
    ],
)
def test_keine_preise_und_keine_terminzusagen(firma, ki, ki_text):
    ki(_ki_antwort(ki_text, anliegen="Fliesen"))
    g, _ = fuehrung.starten(firma)
    assert fuehrung.antworten(g, "Was kostet das und wann können Sie kommen?").text == fuehrung.ERSATZ


def test_hoechstens_acht_runden(firma, ki):
    ki(_ki_antwort("Können Sie das genauer beschreiben?", anliegen="Heizung"))
    g, _ = fuehrung.starten(firma, anrufer_nummer="0301234567")
    for i in range(fuehrung.MAX_RUNDEN - 1):
        assert not fuehrung.antworten(g, f"Beitrag {i}").beendet
    letzte = fuehrung.antworten(g, "noch etwas")
    assert letzte.beendet and Rueckruf.objects.get(gespraech=g).anliegen == "Heizung"


def test_ausfallbetrieb_ohne_ki(firma, ki):
    ki(anthropic.APIConnectionError(request=httpx.Request("POST", "https://bedrock-mantle.eu-central-1.api.aws")))
    g, _ = fuehrung.starten(firma)
    erste = fuehrung.antworten(g, "Hier Meier, die Dachrinne ist abgerissen.")
    assert "Unter welcher Nummer" in erste.text and not erste.beendet
    zweite = fuehrung.antworten(g, "Null eins sieben eins, also 0171 9876543")
    assert zweite.beendet and zweite.text == fuehrung.ABSCHIED
    r = Rueckruf.objects.get(gespraech=g)
    assert r.anliegen == "Hier Meier, die Dachrinne ist abgerissen." and r.rueckrufnummer == "01719876543"
    g.refresh_from_db()
    assert g.ausfallbetrieb and Protokolleintrag.objects.filter(ereignis="telefon.ausfallbetrieb").exists()


def test_eigenes_telefonlimit_fuehrt_in_den_ausfallbetrieb(firma, ki, settings):
    settings.TELEFON_LIMIT_GESPRAECHE_MONAT = 1
    Gespraech.objects.create(firma=firma)  # erstes Gespräch des Monats
    client = ki(_ki_antwort("sollte nie kommen"))
    g, _ = fuehrung.starten(firma, anrufer_nummer="0301234567")
    assert "Nummer, von der Sie anrufen" in fuehrung.antworten(g, "Heizung ist aus").text
    assert client.messages.aufrufe == []


def test_telefon_belastet_das_ki_limit_der_erfassung_nicht(firma, ki, settings):
    """Viele Anrufe dürfen die Belegerfassung nie blockieren: eigener Zähler am Gespräch statt KiVerbrauch."""
    from capture.extraktion import kostenlimit_pruefen
    from capture.models import KiVerbrauch

    settings.KI_LIMIT_VORGAENGE_MONAT = 1
    ki(_ki_antwort("Worum geht es?", name="Weber"))
    g, _ = fuehrung.starten(firma)
    fuehrung.antworten(g, "Hier Weber.")
    fuehrung.antworten(g, "Heizung.")
    g.refresh_from_db()
    assert (g.ki_eingabe, g.ki_ausgabe, g.ausfallbetrieb) == (1800, 160, False)
    assert not KiVerbrauch.objects.filter(firma=firma).exists()
    kostenlimit_pruefen(firma)  # Erfassung weiter frei
    assert fuehrung.monatsverbrauch(firma)["gespraeche"] == 1


def test_aufgelegt(firma):
    g, _ = fuehrung.starten(firma, anrufer_nummer="0301234567")
    r = fuehrung.auflegen(g)
    assert r.anliegen.startswith("Anruf ohne Nachricht") and r.rueckrufnummer == "0301234567"
    unterdrueckt, _ = fuehrung.starten(firma)
    assert fuehrung.auflegen(unterdrueckt) is None
    assert Protokolleintrag.objects.filter(ereignis="telefon.gespraech_ohne_notiz").exists()


def test_rueckrufe_oberflaeche(client_inhaber, firma, inhaber):
    jetzt = timezone.now()
    normal = Rueckruf.objects.create(firma=firma, name="Normal", anliegen="a", erstellt=jetzt)
    dringend = Rueckruf.objects.create(
        firma=firma, name="Dringend", anliegen="b", dringlichkeit="dringend", erstellt=jetzt - timedelta(hours=1)
    )
    seite = client_inhaber.get(reverse("telefon:rueckrufe")).content.decode()
    assert seite.index("Dringend") < seite.index("Normal")
    assert (
        '<span class="zahl" aria-label="2 offen">2</span>' in client_inhaber.get(reverse("web:start")).content.decode()
    )
    client_inhaber.post(reverse("telefon:erledigt", args=[dringend.pk]), {"notiz": "zurückgerufen"})
    dringend.refresh_from_db()
    assert dringend.status == "erledigt" and dringend.erledigt_von == inhaber and dringend.notiz == "zurückgerufen"
    client_inhaber.post(reverse("telefon:erledigt", args=[dringend.pk]), {"aktion": "wieder_oeffnen"})
    dringend.refresh_from_db()
    assert dringend.status == "offen"
    assert Protokolleintrag.objects.filter(ereignis="telefon.rueckruf_erledigt", nutzer=inhaber).exists()
    assert "Normal" in client_inhaber.get(reverse("telefon:rueckruf", args=[normal.pk])).content.decode()


def test_einstellungen_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("telefon:einstellungen")).status_code == 403


def test_einstellungen_speichern(client_inhaber, firma):
    seite = client_inhaber.get(reverse("telefon:einstellungen")).content.decode()
    assert fuehrung.PFLICHTHINWEIS in seite and "Ab 400 Gesprächen im Monat" in seite
    client_inhaber.post(
        reverse("telefon:einstellungen"), {"aktiv": "on", "begruessung": "Moin!", "benachrichtigen": "on"}
    )
    e = Telefonassistent.objects.get(firma=firma)
    assert e.aktiv and e.begruessung == "Moin!" and e.rufnummer == ""  # Nummer vergibt das Belegfluss-Team


def test_loeschfristen(firma):
    from audit.loeschfristen import ausfuehren

    jetzt = timezone.now()
    alt = Gespraech.objects.create(firma=firma, loeschen_ab=jetzt - timedelta(days=1))
    neu = Gespraech.objects.create(firma=firma)
    erledigt_alt = Rueckruf.objects.create(firma=firma, status="erledigt", erledigt_am=jetzt - timedelta(days=91))
    erledigt_neu = Rueckruf.objects.create(firma=firma, status="erledigt", erledigt_am=jetzt - timedelta(days=10))
    offen_alt = Rueckruf.objects.create(firma=firma, erstellt=jetzt - timedelta(days=366))
    offen_neu = Rueckruf.objects.create(firma=firma)
    bericht = ausfuehren()
    assert not Gespraech.objects.filter(pk=alt.pk).exists() and Gespraech.objects.filter(pk=neu.pk).exists()
    assert set(Rueckruf.objects.values_list("pk", flat=True)) == {erledigt_neu.pk, offen_neu.pk}
    assert not Rueckruf.objects.filter(pk__in=[erledigt_alt.pk, offen_alt.pk]).exists()
    assert bericht.gesamt["telefon_gespraeche"] == 1 and bericht.gesamt["rueckrufe"] == 2


def test_unerwarteter_ki_fehler_fuehrt_in_den_ausfallbetrieb(firma, monkeypatch):
    import capture.extraktion

    def kaputt():
        raise RuntimeError("keine AWS-Zugangsdaten")

    monkeypatch.setattr(capture.extraktion, "client_fabrik", kaputt)
    g, _ = fuehrung.starten(firma)
    assert "Unter welcher Nummer" in fuehrung.antworten(g, "Hier Meier, Dachrinne").text


def test_haiku_ohne_mitdenken_fuer_kurze_antwortzeiten(firma, ki, settings):
    client = ki(_ki_antwort("Danke. Worum geht es?", name="Weber"))
    settings.TELEFON_MODELL = "eu.anthropic.claude-haiku-5-5"
    g, _ = fuehrung.starten(firma)
    fuehrung.antworten(g, "Hier Weber.")
    aufruf = client.messages.aufrufe[0]
    assert aufruf["model"] == "eu.anthropic.claude-haiku-5-5" and aufruf["thinking"] == {"type": "disabled"}
    settings.TELEFON_MODELL = "eu.anthropic.claude-sonnet-5-5"
    fuehrung.antworten(g, "Wasserfleck.")
    assert "thinking" not in client.messages.aufrufe[1]
