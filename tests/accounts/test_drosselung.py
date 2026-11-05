"""M1-03: Nach 10 Fehlversuchen je IP oder je Konto in 15 Minuten antwortet die App mit 429 (A5)."""

import pytest
from django.test import override_settings
from django.urls import reverse

from accounts import totp
from accounts.drosselung import client_ip
from accounts.zweifaktor import einrichtung_beginnen, einrichtung_bestaetigen, geheimnis


def _login(client, email, passwort, ip="203.0.113.5"):
    return client.post(reverse("accounts:login"), {"email": email, "passwort": passwort}, REMOTE_ADDR=ip)


@pytest.mark.django_db
def test_login_je_ip_nach_10_fehlversuchen_429(client, inhaber, passwort):
    for i in range(10):
        assert _login(client, f"x{i}@example.org", "falsch").status_code == 200
    antwort = _login(client, inhaber.email, passwort)
    assert antwort.status_code == 429
    assert "_auth_user_id" not in client.session
    # andere IP ist nicht betroffen
    assert _login(client, inhaber.email, passwort, ip="198.51.100.7").status_code == 302


@pytest.mark.django_db
def test_login_je_konto_nach_10_fehlversuchen_429(client, inhaber, passwort):
    for i in range(10):
        _login(client, inhaber.email.upper(), "falsch", ip=f"198.51.100.{i}")
    assert _login(client, inhaber.email, passwort, ip="192.0.2.99").status_code == 429


@pytest.mark.django_db
def test_neun_fehlversuche_sperren_noch_nicht(client, inhaber, passwort):
    for _ in range(9):
        _login(client, inhaber.email, "falsch")
    assert _login(client, inhaber.email, passwort).status_code == 302


@pytest.mark.django_db
def test_zweiter_faktor_nach_10_fehlversuchen_429(client, inhaber, passwort):
    zf = einrichtung_beginnen(inhaber)
    einrichtung_bestaetigen(zf, totp.code_fuer_schritt(geheimnis(zf), totp.aktueller_schritt()))
    zf.refresh_from_db()
    zf.letzter_schritt = None
    zf.save()
    _login(client, inhaber.email, passwort)
    for _ in range(10):
        assert client.post(reverse("accounts:zweiter_faktor"), {"code": "000000"}).status_code == 200
    richtig = totp.code_fuer_schritt(geheimnis(zf), totp.aktueller_schritt())
    assert client.post(reverse("accounts:zweiter_faktor"), {"code": richtig}).status_code == 429
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_zwei_faktor_einrichtung_gedrosselt(client, inhaber, passwort):
    _login(client, inhaber.email, passwort)
    for _ in range(10):
        client.post(reverse("accounts:zweiter_faktor_einrichten"), {"code": "000000"})
    assert client.post(reverse("accounts:zweiter_faktor_einrichten"), {"code": "000000"}).status_code == 429


@pytest.mark.django_db
def test_passwort_reset_gedrosselt(client, inhaber):
    for _ in range(10):
        assert client.post(reverse("accounts:passwort_vergessen"), {"email": inhaber.email}).status_code == 302
    assert client.post(reverse("accounts:passwort_vergessen"), {"email": inhaber.email}).status_code == 429


@pytest.mark.django_db
def test_registrierung_gedrosselt(client):
    for _ in range(10):
        client.post(reverse("accounts:registrieren"), {"einladungscode": "falsch"})
    assert client.post(reverse("accounts:registrieren"), {"einladungscode": "falsch"}).status_code == 429


def test_client_ip_hinter_proxy(rf):
    anfrage = rf.get("/", REMOTE_ADDR="10.0.0.2", HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.9")
    assert client_ip(anfrage) == "10.0.0.2"
    with override_settings(HINTER_PROXY=True):
        assert client_ip(anfrage) == "203.0.113.9"
