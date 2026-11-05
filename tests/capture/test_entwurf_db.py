"""M3-06: Regeln mit Daten aus dem Spiegel und Angebotspositionen aus Lexware."""

from decimal import Decimal

import pytest

from capture.entwurf import regeln_anwenden
from capture.models import Erfassung
from jobs.queue import enqueue
from ledger.models import Artikel, Beleg, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.ki_fake import antwort, ergebnis

pytestmark = pytest.mark.django_db


@pytest.fixture
def spiegel(firma, verbindung):
    bau = Kontakt.objects.create(firma=firma, extern_id="kon-unternehmer", name="Bau AG", kundennummer="10001")
    Artikel.objects.create(
        firma=firma,
        extern_id="art-maler-stunde",
        bezeichnung="Malerarbeiten Facharbeiter",
        einheit="Stunde",
        netto=Decimal("58.00"),
        steuersatz=Decimal("19"),
        typ="SERVICE",
    )
    Artikel.objects.create(
        firma=firma,
        extern_id="art-alt",
        bezeichnung="Archiviert",
        einheit="Stück",
        netto=Decimal("1.00"),
        steuersatz=Decimal("19"),
        typ="PRODUCT",
        archiviert=True,
    )
    Beleg.objects.create(
        firma=firma,
        extern_id="an-0007",
        art="angebot",
        nummer="AN-2026-7",
        kontakt=bau,
        kontakt_name="Bau AG",
        status="offen",
    )
    return firma


def test_extraktion_bis_pruefung_mit_angebot(spiegel, inhaber, ki, worker, lexware_api, ohne_warten):
    e = Erfassung.objects.create(
        firma=spiegel,
        erstellt_von=inhaber,
        kanal="aufnahme",
        status="extrahiert",
        transkript="Bau AG 22 Stunden laut Angebot",
    )
    ki(
        antwort(
            ergebnis(
                angebot_nummer="AN-2026-7",
                positionen=[
                    {
                        "artikel_id": "art-maler-stunde",
                        "beschreibung": "Malerarbeiten",
                        "menge": 22,
                        "einheit": "Stunde",
                        "quelle": "Sprachmemo",
                        "herkunft": "gesprochen",
                    }
                ],
            )
        )
    )
    enqueue("capture.extrahieren", {"erfassung_id": e.pk}, firma=spiegel)
    alle_jobs_ausfuehren(worker)
    e.refresh_from_db()
    assert e.status == "pruefung"
    assert e.entwurf["kunde_extern_id"] == "kon-unternehmer"
    assert e.entwurf["positionen"][0]["netto"] == "58.00"
    assert e.entwurf["summen"]["netto"] == "1276.00"
    assert e.blocker == []
    assert any("Mehraufwand: 2 mehr" in h for h in e.hinweise)  # Angebot: 20 Stunden
    assert e.eingabe == e.ki_ergebnis


def test_archivierter_artikel_gilt_nicht(spiegel):
    e = Erfassung.objects.create(
        firma=spiegel,
        kanal="upload",
        status="pruefung",
        ki_ergebnis=ergebnis(
            positionen=[
                {
                    "artikel_id": "art-alt",
                    "beschreibung": "x",
                    "menge": 1,
                    "einheit": "Stück",
                    "quelle": "q",
                    "herkunft": "notiz",
                }
            ]
        ),
    )
    entwurf = regeln_anwenden(e)
    assert entwurf.positionen[0].netto is None
    assert not entwurf.freigabefaehig


def test_fremde_artikel_und_kunden_bleiben_unsichtbar(spiegel, andere_firma):
    Kontakt.objects.create(firma=andere_firma, extern_id="fremd", name="Fremd GmbH")
    Artikel.objects.create(
        firma=andere_firma,
        extern_id="fremd-art",
        bezeichnung="Fremd",
        einheit="h",
        netto=1,
        steuersatz=19,
        typ="SERVICE",
    )
    e = Erfassung.objects.create(
        firma=spiegel,
        kanal="upload",
        status="pruefung",
        ki_ergebnis=ergebnis(
            kunde="Fremd GmbH",
            positionen=[
                {
                    "artikel_id": "fremd-art",
                    "beschreibung": "x",
                    "menge": 1,
                    "einheit": "h",
                    "quelle": "q",
                    "herkunft": "notiz",
                }
            ],
        ),
    )
    entwurf = regeln_anwenden(e)
    assert entwurf.kunde_extern_id == ""
    assert entwurf.positionen[0].netto is None


def test_angebote_werden_gespiegelt(firma, verbindung, lexware_api, ohne_warten, worker):
    enqueue("ledger.erstimport", {"verbindung_id": verbindung.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    angebot = Beleg.objects.get(firma=firma, extern_id="an-0007")
    assert (angebot.art, angebot.nummer, angebot.status, angebot.offen) == (
        "angebot",
        "AN-2026-7",
        "offen",
        Decimal("0.00"),
    )
    # Angebote zählen nicht als offene Forderung
    from ledger.services import offene_belege

    assert not offene_belege(firma).filter(art="angebot").exists()
