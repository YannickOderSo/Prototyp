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
