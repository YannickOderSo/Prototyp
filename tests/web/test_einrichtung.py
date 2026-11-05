"""M4-03: Onboarding-Assistent (F6)."""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from audit.models import Protokolleintrag
from connectors.models import Verbindung
from dunning.models import Mahnplan, Mahnvorschlag
from ledger.models import Beleg, Kontakt

pytestmark = pytest.mark.django_db


def test_ohne_verbindung_erster_schritt_offen(client_inhaber, firma):
    html = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "1. Lexware verbinden" in html
    assert reverse("connectors:lexware") in html
    assert "Probelauf: Das würde" not in html
    start = client_inhaber.get(reverse("web:start")).content.decode()
    assert "Einrichtung starten" in start


def test_kompletter_ablauf(client_inhaber, firma, verbindung):
    Verbindung.objects.filter(pk=verbindung.pk).update(erstimport_fertig=timezone.now())
    firmenkunde = Kontakt.objects.create(
        firma=firma, extern_id="k1", name="Bau AG", ist_unternehmen_extern=True, email="a@b.example"
    )
    person = Kontakt.objects.create(firma=firma, extern_id="k2", name="Erika", ist_unternehmen_extern=False)
    for i, k in enumerate((firmenkunde, person)):
        Beleg.objects.create(
            firma=firma,
            extern_id=f"b{i}",
            nummer=f"RE{i}",
            kontakt=k,
            offen=Decimal("100"),
            brutto=Decimal("100"),
            status="ueberfaellig",
            faellig_am=timezone.localdate() - timezone.timedelta(days=12),
        )
    html = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "Bei 2 Kunden mit offenen Posten fehlt der Kundentyp" in html
    # Schritt 2: Der Assistent führt zur Liste; der Lexware-Hinweis wird nie automatisch übernommen
    assert reverse("ledger:kundentyp") in html
    assert client_inhaber.post(reverse("web:einrichtung"), {"aktion": "firmen_unternehmer"}).status_code == 302
    firmenkunde.refresh_from_db()
    assert firmenkunde.kundentyp == "unbekannt"
    Kontakt.objects.filter(pk=firmenkunde.pk).update(kundentyp="unternehmer")
    # Schritt 3: Mahnplan-Vorlage
    client_inhaber.post(reverse("web:einrichtung"), {"aktion": "vorlage", "vorlage": "freundlich"})
    plan = Mahnplan.objects.get(firma=firma)
    assert (plan.tage_erinnerung, plan.tage_mahnung1, plan.zinsen_aktiv) == (10, 28, False)
    firma.refresh_from_db()
    assert firma.mahnplan_bestaetigt_am is not None
    # Schritt 4: Probelauf zeigt Vorschlag, speichert nichts
    html = client_inhaber.get(reverse("web:einrichtung")).content.decode()
    assert "Probelauf" in html and "RE0" in html and "Zahlungserinnerung" in html
    assert "1 überfällige Posten würden nicht gemahnt" in html
    assert not Mahnvorschlag.objects.exists()
    antwort = client_inhaber.post(reverse("web:einrichtung"), {"aktion": "abschliessen"})
    assert antwort["Location"] == reverse("web:start")
    firma.refresh_from_db()
    assert firma.einrichtung_fertig_am is not None
    assert Protokolleintrag.objects.filter(ereignis="einrichtung.abgeschlossen").exists()
    start = client_inhaber.get(reverse("web:start")).content.decode()
    assert reverse("web:einrichtung") not in start.split("<main")[1]


def test_ungueltige_vorlage_wird_ignoriert(client_inhaber, firma):
    client_inhaber.post(reverse("web:einrichtung"), {"aktion": "vorlage", "vorlage": "gibtsnicht"})
    assert not Mahnplan.objects.filter(firma=firma).exists()


def test_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("web:einrichtung")).status_code == 403


def test_vorlagen_halten_mindestabstand():
    from web.einrichtung import VORLAGEN

    for vorlage in VORLAGEN.values():
        assert vorlage.tage_mahnung1 - vorlage.tage_erinnerung >= 7
        assert vorlage.tage_mahnung2 - vorlage.tage_mahnung1 >= 7


def test_mahnplan_unter_einstellungen_zaehlt_als_bestaetigt(client_inhaber, firma):
    from dunning.forms import MahnplanForm
    from dunning.services import mahnplan_fuer

    plan = mahnplan_fuer(firma)
    daten = {k: v for k, v in MahnplanForm(instance=plan).initial.items() if v is not None}
    for feld in (
        "erinnerung_aktiv",
        "zinsen_aktiv",
        "pauschale_aktiv",
        "verzugshinweis_auf_rechnungen",
        "bcc_an_firma",
        "automatik_aktiv",
    ):
        if not daten.get(feld):
            daten.pop(feld, None)
    antwort = client_inhaber.post(reverse("dunning:mahnplan"), daten)
    assert antwort.status_code == 302, antwort.content.decode()[:500]
    firma.refresh_from_db()
    assert firma.mahnplan_bestaetigt_am is not None
