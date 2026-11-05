"""M1-04: Generischer IDOR-Test über alle URL-Muster mit IDs (A4).

Jede URL mit Parametern muss hier entweder eine Fabrik haben, die ein Objekt einer FREMDEN Firma
anlegt (dann muss die URL für einen angemeldeten Nutzer der eigenen Firma 404 liefern), oder mit
Begründung als Ausnahme geführt sein. Neue URLs ohne Eintrag lassen den Test scheitern.
"""

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from tests.idor_faelle import AUSNAHMEN, FAELLE


def _alle_muster(resolver=None, praefix=""):
    resolver = resolver or get_resolver()
    for eintrag in resolver.url_patterns:
        if isinstance(eintrag, URLResolver):
            ns = f"{eintrag.namespace}:" if eintrag.namespace else ""
            yield from _alle_muster(eintrag, praefix + ns)
        elif isinstance(eintrag, URLPattern) and eintrag.name:
            yield praefix + eintrag.name, eintrag


def _muster_mit_parametern():
    ergebnis = {}
    for name, muster in _alle_muster():
        if muster.pattern.converters or (getattr(muster.pattern, "regex", None) and muster.pattern.regex.groupindex):
            ergebnis[name] = muster
    return ergebnis


def test_jede_url_mit_parametern_ist_abgedeckt():
    fehlend = sorted(set(_muster_mit_parametern()) - set(FAELLE) - set(AUSNAHMEN))
    assert not fehlend, f"URLs ohne IDOR-Fall oder begründete Ausnahme: {fehlend}"


def test_keine_veralteten_eintraege():
    vorhanden = set(_muster_mit_parametern())
    assert not (set(FAELLE) - vorhanden), "IDOR-Fälle für nicht mehr existierende URLs"
    assert not (set(AUSNAHMEN) - vorhanden), "Ausnahmen für nicht mehr existierende URLs"


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(FAELLE))
@pytest.mark.parametrize("methode", ["get", "post"])
def test_fremde_objekte_liefern_404(name, methode, client_inhaber, andere_firma, fremder_inhaber):
    kwargs = FAELLE[name](andere_firma, fremder_inhaber)
    url = reverse(name, kwargs=kwargs)
    antwort = getattr(client_inhaber, methode)(url)
    assert antwort.status_code in (404, 405), f"{methode.upper()} {url} -> {antwort.status_code}"


@pytest.mark.django_db
@pytest.mark.parametrize("name", sorted(FAELLE))
def test_eigene_objekte_sind_erreichbar(name, client_inhaber, firma, inhaber):
    """Gegenprobe: dieselbe URL mit einem Objekt der eigenen Firma ist kein 404."""
    url = reverse(name, kwargs=FAELLE[name](firma, inhaber))
    assert client_inhaber.get(url).status_code in (200, 302, 405)


def test_firmen_manager_filtert(db, firma, andere_firma):
    from accounts.mandant import hole_oder_404
    from tests.idor_faelle import beispielmodelle

    for modell, fabrik in beispielmodelle():
        eigen = fabrik(firma)
        fremd = fabrik(andere_firma)
        ids = set(modell.objects.fuer(firma).values_list("pk", flat=True))
        assert eigen.pk in ids
        assert fremd.pk not in ids
        assert modell.objects.fuer(None).count() == 0
        assert hole_oder_404(modell, firma, pk=eigen.pk) == eigen
        with pytest.raises(Exception) as fehler:
            hole_oder_404(modell, firma, pk=fremd.pk)
        assert fehler.typename == "Http404"


@pytest.mark.django_db
def test_nutzer_ohne_firma_sieht_keine_fachseiten(client):
    from accounts.models import Nutzer
    from tests.conftest import anmelden_als

    nutzer = Nutzer.objects.create_user(email="ohne@firma.example", password="x")
    anmelden_als(client, nutzer)
    assert client.get(reverse("web:start")).status_code == 200
    assert client.get(reverse("accounts:team")).status_code == 403
