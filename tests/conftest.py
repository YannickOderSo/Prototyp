import pytest


@pytest.fixture(autouse=True)
def _cache_leeren():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def firma(db):
    from accounts.models import Firma

    return Firma.objects.create(name="Malerbetrieb Muster GmbH", reply_to="buero@muster.example")


@pytest.fixture
def andere_firma(db):
    from accounts.models import Firma

    return Firma.objects.create(name="Elektro Fremd KG", reply_to="info@fremd.example")


PASSWORT = "Sehr-sicheres-Passwort-2026"


@pytest.fixture
def passwort():
    return PASSWORT


def _nutzer_mit_rolle(firma, rolle, email):
    from accounts.models import Mitgliedschaft, Nutzer

    nutzer = Nutzer.objects.create_user(email=email, password=PASSWORT, name=email.split("@")[0])
    Mitgliedschaft.objects.create(nutzer=nutzer, firma=firma, rolle=rolle)
    return nutzer


@pytest.fixture
def inhaber(firma):
    return _nutzer_mit_rolle(firma, "inhaber", "inhaber@muster.example")


@pytest.fixture
def freigeber(firma):
    return _nutzer_mit_rolle(firma, "freigeber", "freigeber@muster.example")


@pytest.fixture
def mitarbeiter(firma):
    return _nutzer_mit_rolle(firma, "mitarbeiter", "mitarbeiter@muster.example")


@pytest.fixture
def fremder_inhaber(andere_firma):
    return _nutzer_mit_rolle(andere_firma, "inhaber", "inhaber@fremd.example")


def anmelden_als(client, nutzer):
    """Meldet einen Nutzer vollständig an (Passwort und zweiter Faktor gelten als geprüft)."""
    from accounts.anmeldung import ZWEITER_FAKTOR_OK

    client.force_login(nutzer)
    sitzung = client.session
    sitzung[ZWEITER_FAKTOR_OK] = True
    sitzung.save()
    return client


@pytest.fixture
def client_inhaber(client, inhaber):
    return anmelden_als(client, inhaber)


@pytest.fixture
def client_freigeber(client, freigeber):
    return anmelden_als(client, freigeber)


@pytest.fixture
def client_mitarbeiter(client, mitarbeiter):
    return anmelden_als(client, mitarbeiter)


@pytest.fixture
def lexware_api():
    """respx-Router für die nachgebaute Lexware-API; prüft jede Anfrage auf finalize."""
    import respx

    from tests.lexware_mock import finalize_waechter, standard_routen

    with respx.mock(assert_all_called=False, assert_all_mocked=True) as router:
        standard_routen(router)
        yield router
        for aufruf in router.calls:
            finalize_waechter(aufruf.request)


@pytest.fixture
def ohne_warten(monkeypatch):
    """Keine echten Pausen in Tests (Token-Bucket und Backoff)."""
    import connectors.drossel
    import connectors.lexware

    pausen = []
    monkeypatch.setattr(connectors.drossel.time, "sleep", lambda s: pausen.append(s))
    # Großer Eimer: der Token-Bucket selbst ist in test_lexware.py getrennt getestet
    monkeypatch.setattr(connectors.lexware, "eimer_fuer", lambda _s: connectors.drossel.TokenBucket(10_000, 10_000))
    return pausen


@pytest.fixture
def lexware(lexware_api, ohne_warten):
    from connectors.drossel import TokenBucket
    from connectors.lexware import LexwareConnector

    return LexwareConnector("test-schluessel", eimer=TokenBucket(1000, 1000), schlafen=lambda s: ohne_warten.append(s))


@pytest.fixture
def verbindung(firma):
    from cockpit.krypto import verschluesseln
    from connectors.models import Verbindung

    return Verbindung.objects.create(
        firma=firma,
        schluessel_verschluesselt=verschluesseln("test-schluessel"),
        firmenname_extern="Malerbetrieb Muster GmbH",
    )


@pytest.fixture
def worker():
    from jobs.worker import Worker

    return Worker(name="test", sperrzeit=60)


def alle_jobs_ausfuehren(worker, max_runden=50):
    """Arbeitet alle fälligen Jobs ab (auch Folge-Jobs)."""
    for _ in range(max_runden):
        if not worker.einen_ausfuehren():
            return
    raise AssertionError("Job-Schleife endet nicht")


@pytest.fixture
def mistral(settings):
    """Nachgebaute Mistral-Transkriptions-API (EU)."""
    import respx

    settings.MISTRAL_API_KEY = "test-mistral"
    with respx.mock(assert_all_called=False) as router:
        router.route(url__startswith="http://127.0.0.1:8025").pass_through()
        yield router.post("https://api.mistral.ai/v1/audio/transcriptions")


@pytest.fixture
def ki(monkeypatch):
    """Ersetzt den Bedrock-Client: `ki(antwort1, antwort2, …)` liefert den Fake-Client."""
    import capture.extraktion
    from tests.ki_fake import FakeClient

    def setzen(*antworten):
        client = FakeClient(*antworten)
        monkeypatch.setattr(capture.extraktion, "client_fabrik", lambda: client)
        return client

    return setzen
