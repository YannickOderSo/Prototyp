"""M7-06: Profil mit spielerischem Avatar je Teammitglied (I5)."""

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag

pytestmark = pytest.mark.django_db


def test_jeder_hat_sofort_einen_avatar(inhaber, freigeber):
    assert inhaber.avatar != freigeber.avatar or inhaber.pk == freigeber.pk
    symbol, farbe = inhaber.avatar
    assert symbol and 0 <= farbe <= 5


def test_profil_aendern(client_inhaber, inhaber, firma):
    seite = client_inhaber.get(reverse("accounts:profil")).content.decode()
    assert "Ihr Symbol" in seite and 'value="cat"' in seite and "Abo und Zahlung" in seite
    antwort = client_inhaber.post(
        reverse("accounts:profil"), {"name": "Max Muster", "avatar_symbol": "rocket", "avatar_farbe": 3}
    )
    assert antwort.status_code == 302
    inhaber.refresh_from_db()
    assert (inhaber.name, inhaber.avatar) == ("Max Muster", ("rocket", 3))
    eintrag = Protokolleintrag.objects.get(ereignis="nutzer.profil_geaendert")
    assert eintrag.nutzer == inhaber and set(eintrag.daten["felder"]) == {"name", "avatar_symbol", "avatar_farbe"}
    start = client_inhaber.get(reverse("web:start")).content.decode()
    assert 'class="avatar avatar-farbe-3' in start and "Max Muster" in start


def test_unbekanntes_symbol_abgelehnt(client_mitarbeiter, mitarbeiter):
    antwort = client_mitarbeiter.post(
        reverse("accounts:profil"), {"name": "X", "avatar_symbol": "<script>", "avatar_farbe": 9}
    )
    assert antwort.status_code == 200
    mitarbeiter.refresh_from_db()
    assert mitarbeiter.avatar_symbol == "" and mitarbeiter.avatar_farbe is None


def test_team_zeigt_avatare(client_inhaber):
    assert 'class="avatar avatar-farbe-' in client_inhaber.get(reverse("accounts:team")).content.decode()
