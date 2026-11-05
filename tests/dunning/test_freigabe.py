"""M2-04: Freigabe-Ansicht mit Einzel- und Sammelfreigabe, Verwerfen mit Grund, Mail-Vorschau (D6, D10)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.mail import inhalt
from dunning.models import Mahnplan, Mahnvorschlag
from dunning.vorschlaege import vorschlagslauf
from jobs.models import Job
from tests.dunning.conftest import versendet

pytestmark = pytest.mark.django_db


@pytest.fixture
def vorschlaege(firma, posten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.bankverbindung = "IBAN DE12 3456 7890 1234 5678 90, Sparkasse Musterstadt"
    firma.mahn_signatur = "Max Muster\nMalerbetrieb Muster GmbH"
    firma.save()
    erinnerung = posten(tage=10)
    mahnung = posten(tage=40, offen="1000.00")
    versendet(mahnung, 0, tage_her=30)
    post = posten(tage=10, email="")
    vorschlagslauf(firma)
    return {
        "erinnerung": Mahnvorschlag.objects.get(beleg=erinnerung),
        "mahnung": Mahnvorschlag.objects.get(beleg=mahnung, stufe=1),
        "post": Mahnvorschlag.objects.get(beleg=post),
    }


def test_liste_zeigt_vorschlaege_nach_stufe(client_freigeber, vorschlaege):
    html = client_freigeber.get(reverse("dunning:freigabe")).content.decode()
    assert "Zahlungserinnerung (2)" in html
    assert "1. Mahnung (1)" in html
    assert "Postversand nötig" in html
    assert "40,00 € Pauschale" in html


def test_sammelfreigabe_plant_versand_und_protokolliert(client_inhaber, inhaber, vorschlaege):
    ids = [vorschlaege["erinnerung"].pk, vorschlaege["mahnung"].pk]
    antwort = client_inhaber.post(reverse("dunning:freigeben"), {"vorschlag": ids})
    assert antwort.status_code == 302
    for v in Mahnvorschlag.objects.filter(pk__in=ids):
        assert v.status == "freigegeben"
        assert v.freigegeben_von == inhaber
        assert v.freigegeben_am is not None
    jobs = Job.objects.filter(typ="dunning.versenden")
    assert sorted(j.payload["vorschlag_id"] for j in jobs) == sorted(ids)
    assert Protokolleintrag.objects.filter(ereignis="mahnung.freigegeben").count() == 2
    assert Mahnvorschlag.objects.get(pk=vorschlaege["post"].pk).status == "vorgeschlagen"


def test_einzelfreigabe(client_freigeber, vorschlaege):
    client_freigeber.post(reverse("dunning:freigeben"), {"vorschlag": [vorschlaege["post"].pk]})
    assert Mahnvorschlag.objects.get(pk=vorschlaege["post"].pk).status == "freigegeben"


def test_link_allein_gibt_nichts_frei(client, client_mitarbeiter, vorschlaege):
    url = reverse("dunning:freigeben")
    v = vorschlaege["erinnerung"]
    # GET (z. B. Klick auf einen Link in einer Mail) ändert nie etwas
    assert client_mitarbeiter.get(url, {"vorschlag": v.pk}).status_code == 405
    # Mitarbeiter dürfen nicht freigeben
    assert client_mitarbeiter.post(url, {"vorschlag": [v.pk]}).status_code == 403
    client_mitarbeiter.post(reverse("accounts:logout"))
    # ohne Login: Umleitung zur Anmeldung
    antwort = client.post(url, {"vorschlag": [v.pk]})
    assert antwort.status_code == 302 and "/konto/anmelden/" in antwort["Location"]
    assert Mahnvorschlag.objects.get(pk=v.pk).status == "vorgeschlagen"
    assert not Job.objects.filter(typ="dunning.versenden").exists()


def test_sitzung_ohne_zweiten_faktor_gibt_nicht_frei(client, freigeber, vorschlaege):
    client.force_login(freigeber)  # Passwort ja, zweiter Faktor nein
    client.post(reverse("dunning:freigeben"), {"vorschlag": [vorschlaege["erinnerung"].pk]})
    assert Mahnvorschlag.objects.get(pk=vorschlaege["erinnerung"].pk).status == "vorgeschlagen"


def test_fremde_vorschlaege_werden_ignoriert(client_inhaber, andere_firma, vorschlaege):
    from tests.idor_faelle import _vorschlag

    fremd = _vorschlag(andere_firma)["pk"]
    client_inhaber.post(reverse("dunning:freigeben"), {"vorschlag": [fremd]})
    assert Mahnvorschlag.objects.get(pk=fremd).status == "vorgeschlagen"


def test_bezahlter_oder_pausierter_beleg_wird_nicht_freigegeben(client_inhaber, vorschlaege, heute):
    v = vorschlaege["erinnerung"]
    v.beleg.offen = Decimal("0.00")
    v.beleg.status = "bezahlt"
    v.beleg.save()
    p = vorschlaege["mahnung"]
    p.beleg.mahnpause_bis = heute
    p.beleg.save()
    antwort = client_inhaber.post(reverse("dunning:freigeben"), {"vorschlag": [v.pk, p.pk]}, follow=True)
    html = antwort.content.decode()
    assert "ist nicht mehr offen" in html
    assert "ist pausiert" in html
    assert Mahnvorschlag.objects.filter(status="freigegeben").count() == 0


def test_verwerfen_mit_grund(client_inhaber, vorschlaege):
    v = vorschlaege["erinnerung"]
    client_inhaber.post(reverse("dunning:verwerfen", args=[v.pk]), {"grund": ""})
    assert Mahnvorschlag.objects.get(pk=v.pk).status == "vorgeschlagen"
    client_inhaber.post(reverse("dunning:verwerfen", args=[v.pk]), {"grund": "Ratenzahlung vereinbart"})
    v.refresh_from_db()
    assert v.status == "verworfen"
    assert v.verworfen_grund == "Ratenzahlung vereinbart"
    assert Protokolleintrag.objects.get(ereignis="mahnung.verworfen").daten == {"grund": "Ratenzahlung vereinbart"}
    # kein erneuter Vorschlag für diese Stufe
    assert vorschlagslauf(v.firma).neu == []


def test_vorschau_zeigt_exakt_die_mail(client_freigeber, vorschlaege):
    v = vorschlaege["mahnung"]
    html = client_freigeber.get(reverse("dunning:vorschau", args=[v.pk])).content.decode()
    mail = inhalt(v)
    import html as h

    assert h.escape(mail.text.strip()).splitlines()[0] in html
    for zeile in mail.text.strip().splitlines():
        assert h.escape(zeile) in html
    assert h.escape(mail.betreff) in html
    teil = client_freigeber.get(reverse("dunning:vorschau", args=[v.pk]), HTTP_HX_REQUEST="true").content.decode()
    assert "<html" not in teil


def test_mailinhalt_erinnerung(vorschlaege):
    mail = inhalt(vorschlaege["erinnerung"])
    assert mail.absender == "Malerbetrieb Muster <cockpit@localhost>"
    assert mail.reply_to == "buero@muster.example"
    assert mail.empfaenger == "kunde@example.org"
    assert mail.betreff.startswith("Zahlungserinnerung zu Rechnung RE")
    assert "sicher ist das nur ein Versehen" in mail.text
    assert "1.190,00 €" in mail.text
    assert "IBAN DE12" in mail.text
    assert "gegenstandslos" in mail.text
    assert "Zinsen" not in mail.text
    assert mail.anhang_name.startswith("Rechnung_RE")
    assert mail.bcc == ""


def test_mailinhalt_mahnung_mit_zinsen_und_frist(vorschlaege, heute):
    v = vorschlaege["mahnung"]
    mail = inhalt(v)
    assert mail.betreff.startswith("1. Mahnung zu Rechnung")
    assert "Offener Rechnungsbetrag: 1.000,00 €" in mail.text
    assert "Verzugszinsen (§ 288 BGB, ab" in mail.text
    assert "× 10,52 % p. a. (Basiszins 1,52 % + 9 Prozentpunkte)" in mail.text
    assert "Verzugspauschale (§ 288 Abs. 5 BGB): 40,00 €" in mail.text
    from dunning.mail import euro

    assert f"Gesamtbetrag: {euro(v.gesamt)}" in mail.text
    assert "bis zum 15.11.2026" in mail.text  # heute + 10 Tage
    assert mail.anhang_name.startswith("Mahnung_RE")
    for verboten in ("Schufa", "Inkasso", "Anwalt"):
        assert verboten not in mail.text


def test_eigene_vorlage_und_bcc(firma, vorschlaege):
    plan = Mahnplan.objects.get(firma=firma)
    plan.betreff_0 = "Kleine Erinnerung: {rechnungsnummer}"
    plan.text_0 = "Hallo {kunde}, offen sind {offen}. {firma}"
    plan.bcc_an_firma = True
    plan.save()
    mail = inhalt(vorschlaege["erinnerung"])
    assert mail.betreff.startswith("Kleine Erinnerung: RE")
    assert "offen sind 1.190,00 €" in mail.text
    assert mail.bcc == "buero@muster.example"


def test_navigation_nur_fuer_freigabeberechtigte(client_mitarbeiter):
    assert "Mahnungen" not in client_mitarbeiter.get(reverse("web:start")).content.decode().split("<main")[0]
