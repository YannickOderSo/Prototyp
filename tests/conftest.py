import pytest


@pytest.fixture(autouse=True)
def _cache_leeren():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
