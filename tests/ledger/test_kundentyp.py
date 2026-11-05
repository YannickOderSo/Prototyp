"""M1-10: Kundentyp pflegen (Voraussetzung für D3)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from ledger.models import Beleg, Kontakt


@pytest.fixture
def kontakte(firma):
    offen = Kontakt.objects.create(firma=firma, extern_id="k1", name="Ohne Typ mit Posten", ist_unternehmen_extern=True)
    Beleg.objects.create(firma=firma, extern_id="b1", kontakt=offen, offen=Decimal("10"), status="offen")
    ohne_posten = Kontakt.objects.create(firma=firma, extern_id="k2", name="Ohne Typ ohne Posten")
    fertig = Kontakt.objects.create(firma=firma, extern_id="k3", name="Schon Unternehmer", kundentyp="unternehmer")
    Beleg.objects.create(firma=firma, extern_id="b3", kontakt=fertig, offen=Decimal("10"), status="offen")
    return offen, ohne_posten, fertig


@pytest.mark.django_db
def test_liste_kundentyp_fehlt(client_inhaber, kontakte):
    html = client_inhaber.get(reverse("ledger:kundentyp")).content.decode()
    assert "Ohne Typ mit Posten" in html
    assert "in Lexware als Firma angelegt" in html
    assert "Ohne Typ ohne Posten" not in html
    assert "Schon Unternehmer" not in html
    alle = client_inhaber.get(reverse("ledger:kundentyp"), {"alle": "1"}).content.decode()
    assert "Ohne Typ ohne Posten" in alle


@pytest.mark.django_db
def test_schnellauswahl_per_htmx(client_inhaber, firma, kontakte):
    offen = kontakte[0]
    antwort = client_inhaber.post(
        reverse("ledger:kundentyp_setzen", args=[offen.pk]), {"kundentyp": "unternehmer"}, HTTP_HX_REQUEST="true"
    )
    assert antwort.status_code == 200
    assert "Unternehmer gespeichert" in antwort.content.decode()
    offen.refresh_from_db()
    assert offen.kundentyp == "unternehmer"
    eintrag = Protokolleintrag.objects.get(firma=firma, ereignis="kontakt.kundentyp_gesetzt")
    assert eintrag.daten == {"alt": "unbekannt", "neu": "unternehmer"}
    assert "Ohne Typ mit Posten" not in client_inhaber.get(reverse("ledger:kundentyp")).content.decode()


@pytest.mark.django_db
def test_ohne_htmx_redirect(client_freigeber, kontakte):
    antwort = client_freigeber.post(reverse("ledger:kundentyp_setzen", args=[kontakte[0].pk]), {"kundentyp": "privat"})
    assert antwort.status_code == 302
    kontakte[0].refresh_from_db()
    assert kontakte[0].kundentyp == "privat"


@pytest.mark.django_db
def test_ungueltiger_wert(client_inhaber, kontakte):
    assert (
        client_inhaber.post(
            reverse("ledger:kundentyp_setzen", args=[kontakte[0].pk]), {"kundentyp": "egal"}
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_mitarbeiter_darf_kundentyp_nicht_setzen(client_mitarbeiter, kontakte):
    assert (
        client_mitarbeiter.post(
            reverse("ledger:kundentyp_setzen", args=[kontakte[0].pk]), {"kundentyp": "privat"}
        ).status_code
        == 403
    )
    html = client_mitarbeiter.get(reverse("ledger:kundentyp")).content.decode()
    assert "Privatkunde</button>" not in html


@pytest.mark.django_db
def test_kundenansicht_mit_kundentyp_auswahl(client_inhaber, kontakte):
    html = client_inhaber.get(reverse("ledger:kunde", args=[kontakte[0].pk])).content.decode()
    assert 'value="unternehmer"' in html


@pytest.mark.django_db
def test_startseite_verlinkt_kundentyp(client_inhaber, kontakte):
    html = client_inhaber.get(reverse("web:start")).content.decode()
    assert reverse("ledger:kundentyp") in html
