"""M1-06: Inhaber hinterlegt den Lexware-Schlüssel, die App prüft ihn sofort und speichert ihn verschlüsselt (B1)."""

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from cockpit.krypto import entschluesseln
from connectors.models import Verbindung
from connectors.services import aktive_verbindung, connector_fuer
from tests.lexware_mock import BASIS


@pytest.mark.django_db
def test_schluessel_wird_geprueft_und_verschluesselt_gespeichert(client_inhaber, firma, lexware_api, ohne_warten):
    antwort = client_inhaber.post(reverse("connectors:lexware"), {"schluessel": " geheimer-lexware-schluessel "})
    assert antwort.status_code == 302
    verbindung = Verbindung.objects.get(firma=firma)
    assert verbindung.firmenname_extern == "Malerbetrieb Muster GmbH"
    assert "geheimer-lexware-schluessel" not in verbindung.schluessel_verschluesselt
    assert entschluesseln(verbindung.schluessel_verschluesselt) == "geheimer-lexware-schluessel"
    assert lexware_api.calls.last.request.headers["Authorization"] == "Bearer geheimer-lexware-schluessel"
    seite = client_inhaber.get(reverse("connectors:lexware")).content.decode()
    assert "Malerbetrieb Muster GmbH" in seite
    assert "geheimer-lexware-schluessel" not in seite
    assert Protokolleintrag.objects.filter(firma=firma, ereignis="verbindung.angelegt").exists()
    assert aktive_verbindung(firma) == verbindung


@pytest.mark.django_db
def test_abgelehnter_schluessel_wird_nicht_gespeichert(client_inhaber, firma, lexware_api, ohne_warten):
    lexware_api.get(f"{BASIS}/v1/profile").respond(401)
    antwort = client_inhaber.post(reverse("connectors:lexware"), {"schluessel": "falsch"})
    assert antwort.status_code == 200
    assert "abgelehnt" in antwort.content.decode()
    assert not Verbindung.objects.exists()


@pytest.mark.django_db
def test_nur_inhaber_darf_verbinden(client_freigeber, client_mitarbeiter):
    assert client_freigeber.get(reverse("connectors:lexware")).status_code == 403


@pytest.mark.django_db
def test_mitarbeiter_darf_nicht_verbinden(client_mitarbeiter):
    assert client_mitarbeiter.post(reverse("connectors:lexware"), {"schluessel": "x"}).status_code == 403


@pytest.mark.django_db
def test_trennen_loescht_schluessel(client_inhaber, firma, lexware_api, ohne_warten):
    client_inhaber.post(reverse("connectors:lexware"), {"schluessel": "abc"})
    verbindung = Verbindung.objects.get(firma=firma)
    verbindung.webhook_ids = ["abo-1"]
    verbindung.save()
    lexware_api.delete(f"{BASIS}/v1/event-subscriptions/abo-1").respond(204)
    client_inhaber.post(reverse("connectors:lexware_trennen"))
    verbindung.refresh_from_db()
    assert verbindung.status == Verbindung.Status.GETRENNT
    assert verbindung.schluessel_verschluesselt == ""
    assert aktive_verbindung(firma) is None
    assert Protokolleintrag.objects.filter(firma=firma, ereignis="verbindung.getrennt").exists()


@pytest.mark.django_db
def test_anderes_lexware_konto_wird_abgelehnt(client_inhaber, firma, lexware_api, ohne_warten):
    client_inhaber.post(reverse("connectors:lexware"), {"schluessel": "abc"})
    from tests.lexware_mock import lade

    lexware_api.get(f"{BASIS}/v1/profile").respond(200, json={**lade("profile.json"), "organizationId": "andere"})
    antwort = client_inhaber.post(reverse("connectors:lexware"), {"schluessel": "def"})
    assert "anderen Lexware-Konto" in antwort.content.decode()
    assert entschluesseln(Verbindung.objects.get().schluessel_verschluesselt) == "abc"


@pytest.mark.django_db
def test_connector_fuer_verbindung(firma, lexware_api, ohne_warten):
    from cockpit.krypto import verschluesseln

    verbindung = Verbindung.objects.create(firma=firma, schluessel_verschluesselt=verschluesseln("k"))
    assert connector_fuer(verbindung).test().firmenname == "Malerbetrieb Muster GmbH"


@pytest.mark.django_db
def test_firmendaten_speichern(client_inhaber, firma):
    antwort = client_inhaber.post(
        reverse("web:einstellungen"),
        {
            "name": "Malerbetrieb Muster GmbH",
            "reply_to": "buero@muster.example",
            "email_absender": "Malerbetrieb Muster",
            "bankverbindung": "IBAN DE00",
        },
    )
    assert antwort.status_code == 302
    firma.refresh_from_db()
    assert firma.email_absender == "Malerbetrieb Muster"
    assert Protokolleintrag.objects.filter(firma=firma, ereignis="einstellung.geaendert").exists()


@pytest.mark.django_db
def test_mitarbeiter_sieht_keine_firmendaten(client_mitarbeiter, firma):
    antwort = client_mitarbeiter.post(reverse("web:einstellungen"), {"name": "Gehackt"})
    assert antwort.status_code == 200
    firma.refresh_from_db()
    assert firma.name != "Gehackt"
