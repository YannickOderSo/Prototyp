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
    assert Beleg.objects.filter(status__in=Beleg.OFFENE_STATUS).exclude(art="angebot").count() == 10
    assert Beleg.objects.filter(art="angebot").count() == 6
    stufen = set(Mahnvorschlag.objects.filter(status="vorgeschlagen").values_list("stufe", flat=True))
    assert stufen == {0, 1}
    rechnung = Erfassung.objects.get(transkript__contains="Sockelleiste")
    assert rechnung.status == "pruefung" and rechnung.blocker  # Sockelleiste ohne Preis
    angebot = Erfassung.objects.get(transkript__contains="Praxis Dr. Sommer")
    assert angebot.entwurf["belegart"] == "angebot" and angebot.blocker == []
    assert not Job.objects.exists() and mailoutbox == []
    with pytest.raises(CommandError, match="existiert bereits"):
        call_command("demo_daten")


def test_statische_demo(settings, tmp_path):
    """Klick-Demo für GitHub Pages: relative Links, kein Token, kein htmx, Hinweis-Banner."""
    from datenimport.models import ImportVorgang

    settings.DEBUG = True
    call_command("demo_daten")
    assert ImportVorgang.objects.get().status == "vorschau"
    call_command("statische_demo", str(tmp_path / "demo"))
    ziel = tmp_path / "demo"
    seiten = list(ziel.rglob("*.html"))
    assert len(seiten) > 20
    for seite in seiten:
        html = seite.read_text()
        assert "Klick-Demo" in html
        assert "csrfmiddlewaretoken" not in html and "X-CSRFToken" not in html
        assert "htmx" not in html
        assert 'href="/' not in html and 'src="/' not in html and 'action="/' not in html
        assert "demo-kein-echter-schluessel" not in html
    assert (ziel / "index.html").exists() and (ziel / "posten" / "index.html").exists()
    assert (ziel / "static" / "web" / "style.css").exists() and (ziel / "static" / "demo" / "demo.js").exists()
    assert (ziel / "import" / "vorlage" / "kunden.csv").exists()
    assert (ziel / "static" / "web" / "fonts" / "inter-latin-wght-normal.woff2").exists()
    assert not (ziel / "konto" / "sicherheit").exists() and not (ziel / "einstellungen" / "verbindung").exists()
    assert (ziel / "konto" / "profil" / "index.html").exists()
    # Cockpit-Reiter und Zeiträume der Statistik als eigene Seiten, Links umgeschrieben
    assert (ziel / "index-ansicht-angebote.html").exists() and (
        ziel / "berichte" / "index-zeitraum-monat.html"
    ).exists()
    assert 'href="index-ansicht-angebote.html"' in (ziel / "index.html").read_text()
    posten = (ziel / "posten" / "index.html").read_text()
    assert 'href="../static/web/style.css"' in posten


def test_statische_demo_nur_mit_debug(settings, tmp_path):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DJANGO_DEBUG"):
        call_command("statische_demo", str(tmp_path))
