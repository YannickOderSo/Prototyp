"""M1-02: TOTP-Zweitfaktor ist Pflicht, mit Replay-Schutz und gehashten Wiederherstellungscodes (A2)."""

import base64
import re
import time

import pytest
from django.urls import reverse

from accounts import totp
from accounts.codes import code_hash
from accounts.models import ZweiFaktor
from accounts.zweifaktor import (
    code_pruefen,
    einrichtung_beginnen,
    einrichtung_bestaetigen,
    geheimnis,
    wiederherstellungscode_einloesen,
)

RFC_GEHEIMNIS = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize(
    ("zeit", "erwartet"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_rfc6238_testvektoren_sha1(zeit, erwartet):
    assert totp.code_fuer_schritt(RFC_GEHEIMNIS, zeit // 30, stellen=8) == erwartet


def test_sechsstellig_und_toleranz():
    jetzt = 1_800_000_000.0
    schritt = totp.aktueller_schritt(jetzt)
    for versatz in (-1, 0, 1):
        code = totp.code_fuer_schritt(RFC_GEHEIMNIS, schritt + versatz)
        assert len(code) == 6
        assert totp.passender_schritt(RFC_GEHEIMNIS, code, None, jetzt) == schritt + versatz
    zu_alt = totp.code_fuer_schritt(RFC_GEHEIMNIS, schritt - 2)
    assert totp.passender_schritt(RFC_GEHEIMNIS, zu_alt, None, jetzt) is None
    assert totp.passender_schritt(RFC_GEHEIMNIS, "12ab", None, jetzt) is None


def test_provisioning_uri():
    uri = totp.provisioning_uri("ABC", "a@b.example")
    assert uri.startswith("otpauth://totp/Belegfluss:a%40b.example?")
    assert "secret=ABC" in uri


def _aktueller_code(zf, versatz=0):
    return totp.code_fuer_schritt(geheimnis(zf), totp.aktueller_schritt() + versatz)


@pytest.mark.django_db
def test_geheimnis_ist_verschluesselt_gespeichert(inhaber):
    zf = einrichtung_beginnen(inhaber)
    roh = ZweiFaktor.objects.get(pk=zf.pk).geheimnis_verschluesselt
    assert geheimnis(zf) not in roh
    assert len(geheimnis(zf)) == 32


@pytest.mark.django_db
def test_replay_schutz_jeder_code_nur_einmal(inhaber):
    zf = einrichtung_beginnen(inhaber)
    code = _aktueller_code(zf)
    assert code_pruefen(zf, code)
    assert not code_pruefen(zf, code), "derselbe Code darf nicht zweimal gelten"
    # auch ältere Schritte sind danach gesperrt
    assert not code_pruefen(zf, _aktueller_code(zf, -1))


@pytest.mark.django_db
def test_wiederherstellungscodes_gehasht_und_einmalig(inhaber):
    zf = einrichtung_beginnen(inhaber)
    codes = einrichtung_bestaetigen(zf, _aktueller_code(zf))
    assert codes is not None and len(codes) == 10
    gespeichert = ZweiFaktor.objects.get(pk=zf.pk).wiederherstellungscodes_hash
    assert codes[0] not in str(gespeichert)
    assert code_hash(codes[0]) in gespeichert
    assert wiederherstellungscode_einloesen(zf, codes[0].lower())
    assert not wiederherstellungscode_einloesen(zf, codes[0])
    assert len(ZweiFaktor.objects.get(pk=zf.pk).wiederherstellungscodes_hash) == 9


@pytest.mark.django_db
def test_passwort_allein_gibt_keinen_zugriff(client, inhaber, passwort):
    antwort = client.post(reverse("accounts:login"), {"email": inhaber.email, "passwort": passwort})
    assert antwort["Location"] == reverse("accounts:zweiter_faktor_einrichten")
    assert "_auth_user_id" not in client.session
    assert client.get(reverse("web:start")).status_code == 302


@pytest.mark.django_db
def test_kompletter_ablauf_einrichten_und_spaeter_anmelden(client, inhaber, passwort):
    client.post(reverse("accounts:login"), {"email": inhaber.email, "passwort": passwort})
    seite = client.get(reverse("accounts:zweiter_faktor_einrichten"))
    assert seite.status_code == 200
    assert "<svg" in seite.content.decode()
    zf = ZweiFaktor.objects.get(nutzer=inhaber)
    antwort = client.post(reverse("accounts:zweiter_faktor_einrichten"), {"code": "000000"})
    assert "_auth_user_id" not in client.session
    antwort = client.post(reverse("accounts:zweiter_faktor_einrichten"), {"code": _aktueller_code(zf)})
    assert antwort["Location"] == reverse("accounts:wiederherstellungscodes")
    codes_seite = client.get(reverse("accounts:wiederherstellungscodes")).content.decode()
    codes = re.findall(r"<code>([A-Z0-9-]+)</code>", codes_seite)
    assert len(codes) == 10
    # nur einmal anzeigen
    assert client.get(reverse("accounts:wiederherstellungscodes")).status_code == 302
    assert client.get(reverse("web:start")).status_code == 200

    # Später: erneute Anmeldung fragt nach dem Code
    client.post(reverse("accounts:logout"))
    antwort = client.post(
        reverse("accounts:login") + "?next=/konto/sicherheit/", {"email": inhaber.email, "passwort": passwort}
    )
    assert antwort["Location"] == reverse("accounts:zweiter_faktor")
    assert client.post(reverse("accounts:zweiter_faktor"), {"code": "123456"}).status_code == 200
    assert "_auth_user_id" not in client.session
    zf.refresh_from_db()
    zf.letzter_schritt = None
    zf.save()
    antwort = client.post(reverse("accounts:zweiter_faktor"), {"code": _aktueller_code(zf, 1)})
    assert antwort["Location"] == "/konto/sicherheit/"
    assert client.get(reverse("web:start")).status_code == 200

    # Mit Wiederherstellungscode
    client.post(reverse("accounts:logout"))
    client.post(reverse("accounts:login"), {"email": inhaber.email, "passwort": passwort})
    antwort = client.post(reverse("accounts:zweiter_faktor"), {"code": codes[3]})
    assert antwort.status_code == 302
    assert client.get(reverse("web:start")).status_code == 200


@pytest.mark.django_db
def test_zwei_faktor_seiten_ohne_vorlogin(client):
    assert client.get(reverse("accounts:zweiter_faktor"))["Location"] == reverse("accounts:login")
    assert client.get(reverse("accounts:zweiter_faktor_einrichten"))["Location"] == reverse("accounts:login")


@pytest.mark.django_db
def test_vorlogin_laeuft_ab(client, inhaber, passwort, monkeypatch):
    client.post(reverse("accounts:login"), {"email": inhaber.email, "passwort": passwort})
    echt = time.time
    monkeypatch.setattr(time, "time", lambda: echt() + 11 * 60)
    assert client.get(reverse("accounts:zweiter_faktor_einrichten"))["Location"] == reverse("accounts:login")


@pytest.mark.django_db
def test_sicherheit_neue_codes(client_inhaber, inhaber):
    zf = einrichtung_beginnen(inhaber)
    einrichtung_bestaetigen(zf, _aktueller_code(zf))
    zf.letzter_schritt = None
    zf.save()
    alt = list(zf.wiederherstellungscodes_hash)
    assert client_inhaber.get(reverse("accounts:sicherheit")).status_code == 200
    antwort = client_inhaber.post(reverse("accounts:sicherheit"), {"code": _aktueller_code(zf)})
    assert antwort["Location"] == reverse("accounts:wiederherstellungscodes")
    zf.refresh_from_db()
    assert set(zf.wiederherstellungscodes_hash).isdisjoint(alt)
