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
