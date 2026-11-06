"""M6-04/05: Vorschau, Freigabe und Anlage von Kunden und Artikeln in Lexware (H3–H6, ADR-008)."""

import json
from decimal import Decimal

import httpx
import pytest
from django.utils import timezone

from audit.models import Protokolleintrag
from datenimport import services
from datenimport.models import ImportVorgang
from datenimport.services import ImportNichtMoeglich
from ledger.models import Artikel, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.lexware_mock import BASIS

pytestmark = pytest.mark.django_db

KUNDEN_CSV = (
    "Kundennr;Firma;Vorname;Nachname;E-Mail;Straße;PLZ;Ort;Kundentyp\n"
    "K-1;Bau AG;;;rechnung@bau-ag.example;Bahnhofstr. 1;10115;Berlin;Unternehmer\n"  # Dublette (Spiegel)
    "K-2;Dach & Co KG;Paul;Polier;info@dach.example;Ring 3;20095;Hamburg;Firma\n"
    "K-3;;Erika;Musterfrau;erika@example.org;Weg 2;80331;München;privat\n"
    "K-4;;;;keine@example.org;;;;\n"  # Fehler: Name fehlt
    "K-5;dach & co  kg;;;;;;;\n"  # Dublette in der Datei
    "K-6;Kaputt GmbH;;;kein-mail;;;;\n"  # Fehler: E-Mail
).encode()


def _vorgang(firma, inhaber, art, inhalt, dateiname="daten.csv"):
    vorgang = services.hochladen(firma, inhaber, art, dateiname, inhalt)
    fehlend = services.zuordnung_speichern(vorgang, vorgang.zuordnung, {}, kundentyp_uebernehmen=False)
    assert fehlend == []
    return vorgang


@pytest.fixture
def spiegel(firma):
    Kontakt.objects.create(firma=firma, extern_id="kon-1", name="Bau AG", email="rechnung@bau-ag.example")
    Artikel.objects.create(
        firma=firma,
        extern_id="art-1",
        bezeichnung="Malerstunde",
        einheit="Stunde",
        netto=Decimal("58.00"),
        steuersatz=Decimal("19"),
        artikelnummer="M-1",
    )


def test_kunden_vorschau_neu_dublette_fehler(firma, inhaber, spiegel, verbindung):
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    assert vorgang.status == ImportVorgang.Status.VORSCHAU
    status = {z["nr"]: (z["status"], z["grund"]) for z in vorgang.vorschau}
    assert status[2] == ("dublette", "Schon in Lexware vorhanden")
    assert status[3] == ("neu", "")
    assert status[4] == ("neu", "")
    assert status[5][0] == "fehler" and "Name fehlt" in status[5][1]
    assert status[6] == ("dublette", "Doppelt in der Datei (Zeile 3)")
    assert status[7][0] == "fehler"
    dach = next(z for z in vorgang.vorschau if z["nr"] == 3)["daten"]
    assert dach["ist_firma"] is True
    assert (dach["ansprechpartner_vorname"], dach["ansprechpartner_nachname"]) == ("Paul", "Polier")
    erika = next(z for z in vorgang.vorschau if z["nr"] == 4)["daten"]
    assert erika["ist_firma"] is False and erika["vorname"] == "Erika" and erika["kundentyp"] == "privat"
    assert Protokolleintrag.objects.filter(ereignis="import.hochgeladen").count() == 1


def test_pflichtfelder_fehlen_keine_vorschau(firma, inhaber):
    vorgang = services.hochladen(firma, inhaber, "artikel", "a.csv", b"Text;Betrag\nX;1\n")
    fehlend = services.zuordnung_speichern(vorgang, {}, {}, False)
    assert fehlend and vorgang.status == ImportVorgang.Status.ZUORDNUNG and vorgang.vorschau == []


def test_freigabe_mit_gestoerter_verbindung_nicht_moeglich(firma, inhaber, spiegel, verbindung):
    """Verbindung mit Fehler (z. B. Schlüssel abgelehnt): Kunden sollen in Lexware entstehen, nicht still lokal."""
    verbindung.status = "fehler"
    verbindung.save()
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    with pytest.raises(ImportNichtMoeglich, match="Verbindung"):
        services.freigeben(vorgang, inhaber)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.VORSCHAU


@pytest.fixture
def kontakt_api(lexware_api, ohne_warten):
    angelegt: list[dict] = []

    def anlegen(request: httpx.Request) -> httpx.Response:
        angelegt.append(json.loads(request.content))
        return httpx.Response(200, json={"id": f"neu-{len(angelegt)}", "version": 1})

    def laden(request: httpx.Request, kid: str) -> httpx.Response:
        koerper = angelegt[int(kid.split("-")[1]) - 1]
        return httpx.Response(200, json={**koerper, "id": kid, "roles": {"customer": {"number": 10100}}})

    lexware_api.post(f"{BASIS}/v1/contacts").mock(side_effect=anlegen)
    lexware_api.get(url__regex=rf"{BASIS}/v1/contacts/(?P<kid>neu-\d+)$").mock(side_effect=laden)
    return angelegt


def test_kunden_anlegen_per_job(firma, inhaber, spiegel, verbindung, kontakt_api, worker):
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.freigeben(vorgang, inhaber)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FREIGEGEBEN and vorgang.freigegeben_von == inhaber
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG
    assert vorgang.ergebnis["angelegt"] == 2 and vorgang.ergebnis["fehler"] == 0
    assert len(kontakt_api) == 2  # nur die neuen Zeilen, keine Dubletten oder Fehler
    dach, erika = kontakt_api
    assert dach["company"] == {
        "name": "Dach & Co KG",
        "contactPersons": [
            {"lastName": "Polier", "primary": True, "firstName": "Paul", "emailAddress": "info@dach.example"}
        ],
    }
    assert dach["note"] == "Kundennummer aus Excel: K-2"
    assert erika["person"] == {"lastName": "Musterfrau", "firstName": "Erika"}
    kontakt = Kontakt.objects.get(firma=firma, extern_id="neu-2")
    assert kontakt.name == "Erika Musterfrau" and kontakt.excel_nummer == "K-3"
    assert "80331 München" in kontakt.adresse
    assert kontakt.kundentyp == "unbekannt"  # Kundentyp nur, wenn ausdrücklich übernommen
    assert Protokolleintrag.objects.filter(ereignis="lexware.kontakt_angelegt").count() == 2
    assert Protokolleintrag.objects.filter(ereignis="import.fertig").count() == 1
    assert not Protokolleintrag.objects.filter(ereignis="kontakt.kundentyp_gesetzt").exists()


def test_kundentyp_nur_nach_bestaetigung(firma, inhaber, verbindung, kontakt_api, worker):
    vorgang = services.hochladen(firma, inhaber, "kunden", "k.csv", KUNDEN_CSV)
    services.zuordnung_speichern(vorgang, vorgang.zuordnung, {}, kundentyp_uebernehmen=True)
    services.freigeben(vorgang, inhaber)
    alle_jobs_ausfuehren(worker)
    erika = Kontakt.objects.get(firma=firma, excel_nummer="K-3")
    assert erika.kundentyp == "privat"
    eintrag = Protokolleintrag.objects.get(ereignis="kontakt.kundentyp_gesetzt", objekt_id=str(erika.pk))
    assert eintrag.nutzer == inhaber and eintrag.daten["per"] == "import"
    assert Kontakt.objects.get(firma=firma, excel_nummer="K-2").kundentyp == "unternehmer"  # „Firma“


def test_neuversuch_legt_nichts_doppelt_an(firma, inhaber, spiegel, verbindung, kontakt_api, worker):
    """Absturz nach der ersten Anlage: Der Neuversuch überspringt die schon vermerkte Zeile."""
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.freigeben(vorgang, inhaber)
    vorgang.refresh_from_db()
    vorgang.ergebnis["zeilen"]["3"] = {"id": "neu-alt"}  # Zeile 3 wurde vor dem Absturz angelegt
    vorgang.save(update_fields=["ergebnis"])
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG
    assert [k.get("person", k.get("company"))["lastName" if "person" in k else "name"] for k in kontakt_api] == [
        "Musterfrau"
    ]
    assert vorgang.ergebnis["angelegt"] == 2


def test_voruebergehender_fehler_wird_wiederholt(firma, inhaber, spiegel, verbindung, lexware_api, ohne_warten, worker):
    """503 bis zur Erschöpfung der Connector-Wiederholungen: Der Job läuft erneut, nichts doppelt."""
    zaehler = {"n": 0}

    def anlegen(request: httpx.Request) -> httpx.Response:
        zaehler["n"] += 1
        if 2 <= zaehler["n"] <= 6:  # zweite Zeile: mehrere 503 hintereinander
            return httpx.Response(503)
        return httpx.Response(200, json={"id": f"neu-{zaehler['n']}"})

    lexware_api.post(f"{BASIS}/v1/contacts").mock(side_effect=anlegen)
    lexware_api.get(url__regex=rf"{BASIS}/v1/contacts/neu-\d+$").respond(404)
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.freigeben(vorgang, inhaber)
    for _ in range(5):
        alle_jobs_ausfuehren(worker)
        vorgang.refresh_from_db()
        if vorgang.status == ImportVorgang.Status.FERTIG:
            break
        from jobs.models import Job

        Job.objects.update(naechster_versuch=timezone.now())
    assert vorgang.status == ImportVorgang.Status.FERTIG
    assert vorgang.ergebnis["angelegt"] == 2
    assert Kontakt.objects.filter(firma=firma, extern_id__startswith="neu-").count() == 2


def test_dauerhafter_fehler_je_zeile_sichtbar(firma, inhaber, verbindung, lexware_api, ohne_warten, worker):
    antworten = iter(
        [
            httpx.Response(400, json={"message": "Missing entity"}),
            httpx.Response(200, json={"id": "neu-8"}),
            httpx.Response(200, json={"id": "neu-9"}),
        ]
    )
    lexware_api.post(f"{BASIS}/v1/contacts").mock(side_effect=lambda _r: next(antworten))
    lexware_api.get(url__regex=rf"{BASIS}/v1/contacts/neu-\d+$").respond(404)
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV.replace(b"K-1;Bau AG", b"K-1;Neu AG"))
    services.freigeben(vorgang, inhaber)
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG
    zeilen = vorgang.ergebnis["zeilen"]
    assert "abgelehnt" in zeilen["2"]["fehler"]
    assert zeilen["3"] == {"id": "neu-8"} and zeilen["4"] == {"id": "neu-9"}
    assert vorgang.ergebnis["fehler"] == 1 and vorgang.ergebnis["angelegt"] == 2


def test_api_schluessel_abgelehnt_bricht_ab(firma, inhaber, spiegel, verbindung, lexware_api, ohne_warten, worker):
    lexware_api.post(f"{BASIS}/v1/contacts").respond(401)
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.freigeben(vorgang, inhaber)
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FREIGEGEBEN  # nicht „fertig“: nichts angelegt
    assert vorgang.ergebnis["zeilen"] == {}
    assert not services.job_aktiv(vorgang)
    # Ohne aktive Verbindung kein Fortsetzen; nach neuem Schlüssel geht es weiter
    with pytest.raises(ImportNichtMoeglich, match="Verbindung"):
        services.fortsetzen(vorgang, inhaber)
    verbindung.refresh_from_db()
    verbindung.status, verbindung.fehler = "aktiv", ""
    verbindung.save()
    zaehler = iter(range(1, 10))
    lexware_api.post(f"{BASIS}/v1/contacts").mock(
        side_effect=lambda _r: httpx.Response(200, json={"id": f"neu-{next(zaehler)}"})
    )
    lexware_api.get(url__regex=rf"{BASIS}/v1/contacts/neu-\d+$").respond(404)
    services.fortsetzen(vorgang, inhaber)
    with pytest.raises(ImportNichtMoeglich, match="läuft bereits"):
        services.fortsetzen(vorgang, inhaber)
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG and vorgang.ergebnis["angelegt"] == 2
    assert Protokolleintrag.objects.filter(ereignis="import.fortgesetzt", nutzer=inhaber).exists()


ARTIKEL_CSV = (
    "Art.-Nr.;Bezeichnung;Einheit;Preis netto;Preis brutto;MwSt\n"
    "M-1;Malerstunde;Stunde;58,00;;19%\n"  # Dublette
    "M-2;Tapete Raufaser;Rolle;;11,90;19\n"
    "M-3;Fachbuch;Stück;24,30;;7\n"
    "M-4;Ohne Satz;Stück;10;;16\n"  # Fehler: 16 % gibt es nicht
    "M-5;Fahrtpauschale;;35;;\n"  # Einheit und Satz aus Standardwerten
).encode()


def test_artikel_vorschau_und_anlage(firma, inhaber, spiegel, verbindung, lexware_api, ohne_warten, worker):
    vorgang = services.hochladen(firma, inhaber, "artikel", "a.csv", ARTIKEL_CSV)
    services.zuordnung_speichern(
        vorgang, vorgang.zuordnung, {"einheit": "pauschal", "steuersatz": "19", "typ": "SERVICE"}, False
    )
    status = {z["nr"]: z["status"] for z in vorgang.vorschau}
    assert status == {2: "dublette", 3: "neu", 4: "neu", 5: "fehler", 6: "neu"}
    tapete = next(z for z in vorgang.vorschau if z["nr"] == 3)["daten"]
    assert tapete["netto"] == "10.00"  # 11,90 brutto / 1,19
    fahrt = next(z for z in vorgang.vorschau if z["nr"] == 6)["daten"]
    assert (fahrt["einheit"], fahrt["steuersatz"], fahrt["typ"]) == ("pauschal", "19", "SERVICE")

    zaehler = iter(range(1, 10))
    route = lexware_api.post(f"{BASIS}/v1/articles").mock(
        side_effect=lambda _r: httpx.Response(200, json={"id": f"art-neu-{next(zaehler)}"})
    )
    services.freigeben(vorgang, inhaber)
    alle_jobs_ausfuehren(worker)
    vorgang.refresh_from_db()
    assert vorgang.status == ImportVorgang.Status.FERTIG and vorgang.ergebnis["angelegt"] == 3
    koerper = [json.loads(c.request.content) for c in route.calls]
    assert koerper[0]["price"] == {"netPrice": 10.0, "leadingPrice": "NET", "taxRate": 19}
    assert koerper[1]["price"]["taxRate"] == 7
    buch = Artikel.objects.get(firma=firma, artikelnummer="M-3")
    assert buch.netto == Decimal("24.30") and buch.steuersatz == Decimal("7")
    assert Protokolleintrag.objects.filter(ereignis="lexware.artikel_angelegt").count() == 3


def test_freigabe_berechnet_vorschau_neu(firma, inhaber, verbindung, lexware_api, ohne_warten):
    """Zwischen Vorschau und Freigabe in Lexware angelegt: wird zur Dublette, nicht doppelt angelegt."""
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    assert vorgang.anzahl("neu") == 3
    Kontakt.objects.create(firma=firma, extern_id="spaeter", name="Bau AG")
    Kontakt.objects.create(firma=firma, extern_id="spaeter2", name="Dach & Co KG")
    Kontakt.objects.create(firma=firma, extern_id="spaeter3", name="Erika Musterfrau")
    with pytest.raises(ImportNichtMoeglich, match="keine neuen"):
        services.freigeben(vorgang, inhaber)


def test_verwerfen_und_doppelte_freigabe(firma, inhaber, spiegel, verbindung, kontakt_api, worker):
    vorgang = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.freigeben(vorgang, inhaber)
    with pytest.raises(ImportNichtMoeglich):
        services.freigeben(vorgang, inhaber)
    with pytest.raises(ImportNichtMoeglich):
        services.verwerfen(vorgang, inhaber)
    anderer = _vorgang(firma, inhaber, "kunden", KUNDEN_CSV)
    services.verwerfen(anderer, inhaber)
    anderer.refresh_from_db()
    assert anderer.status == ImportVorgang.Status.VERWORFEN
    with pytest.raises(ImportNichtMoeglich):
        services.zuordnung_speichern(vorgang, {}, {}, False)
