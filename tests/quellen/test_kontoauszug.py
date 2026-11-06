"""M9-05/06 (K6–K8): Kontoauszug hochladen, Zahlungen zuordnen, Freigabe und Versand mit Blick auf den Kontoauszug."""

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.core import mail
from django.urls import reverse

from audit.models import Protokolleintrag
from ledger.models import Beleg, Kontakt
from quellen import bank, zahlungen
from quellen.models import Kontoauszug, Zahlung
from quellen.zahlungen import nummer_im_text
from tests.quellen.hilfen import datei

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture(autouse=True)
def heute():
    import time_machine

    with time_machine.travel(datetime(2026, 11, 5, 7, 0, tzinfo=ZoneInfo("Europe/Berlin")), tick=False):
        yield date(2026, 11, 5)


@pytest.fixture
def posten(firma):
    def neu(nummer, kunde, offen, quelle="kopie", **extra):
        kontakt, _ = Kontakt.objects.get_or_create(
            firma=firma,
            name=kunde,
            defaults={"extern_id": f"lokal-{kunde}", "kundentyp": "unternehmer", "email": "buero@kunde.example"},
        )
        return Beleg.objects.create(
            firma=firma,
            extern_id=f"{quelle}-{nummer}",
            nummer=nummer,
            kontakt=kontakt,
            kontakt_name=kunde,
            belegdatum=date(2026, 10, 1),
            faellig_am=extra.pop("faellig_am", date(2026, 10, 15)),
            brutto=D(offen),
            offen=D(offen),
            status="ueberfaellig",
            quelle=quelle,
            **extra,
        )

    return neu


# ------------------------------------------------------------------ Lesen (K6)


def test_camt053_nur_gebuchte_gutschriften():
    a = bank.lesen("auszug.xml", datei("camt053.xml"))
    assert (a.format, a.konto, a.bis, a.abbuchungen) == ("camt053", "DE89 •••• 3000", date(2026, 11, 4), 2)
    assert [(u.betrag, u.zahler) for u in a.umsaetze] == [
        (D("1642.00"), "Huber Hausverwaltung GmbH"),
        (D("1000.00"), "Bau AG"),  # Sammelbuchung aufgeteilt
        (D("500.00"), "Dach KG"),
    ]
    assert a.umsaetze[0].zahler_konto == "DE02 •••• 2051" and "Telekom" not in str(a.umsaetze)
    assert a.umsaetze[2].verwendungszweck == "RF18539007547034"  # strukturierte Referenz
    assert "DE02120300000000202051" not in str(a)  # volle IBAN wird nicht weitergereicht


def test_camt052_neue_version_ohne_vorgemerkte():
    a = bank.lesen("intraday.xml", datei("camt052_v8.xml"))
    assert a.format == "camt052" and a.vorgemerkt == 1 and len(a.umsaetze) == 1
    assert (a.umsaetze[0].zahler, a.umsaetze[0].buchungsdatum) == ("Lindner Immobilien", date(2026, 11, 5))


@pytest.mark.parametrize(
    ("name", "erwartet"),
    [
        ("sparkasse.csv", [(D("1642.00"), "Huber Hausverwaltung GmbH", "RE-2026-0412 Malerarbeiten Gebäude")]),
        ("dkb.csv", [(D("1000.00"), "Bau AG", "Rechnung 2026/0500")]),
        ("deutsche_bank.csv", [(D("2142.00"), "Weber Elektro", "RE-2026-0412")]),
    ],
)
def test_csv_der_banken(name, erwartet):
    a = bank.lesen(name, datei(name))
    assert a.format == "csv" and a.abbuchungen == 1
    assert [(u.betrag, u.zahler, u.verwendungszweck) for u in a.umsaetze] == erwartet


def test_unlesbare_dateien():
    with pytest.raises(bank.AuszugFehler):
        bank.lesen("x.xml", datei("angriff_dtd.xml"))
    with pytest.raises(bank.AuszugFehler, match="Buchungstag und Betrag"):
        bank.lesen("x.csv", b"Name;Telefon\nMeier;123\n")
    with pytest.raises(bank.AuszugFehler, match="kein Kontoauszug"):
        bank.lesen("x.xml", datei("xrechnung_cii.xml"))


def test_doppelt_hochladen_und_gleiche_zahlungen(firma, inhaber):
    erst = zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    zweit = zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    assert (erst.neu, zweit.neu, zweit.doppelt) == (3, 0, 3) and Zahlung.objects.count() == 3
    zeile = "04.11.2026;Bau AG;Abschlag;100,00\n"
    csv = ("Buchungstag;Auftraggeber;Verwendungszweck;Betrag\n" + zeile + zeile).encode()
    assert zahlungen.einlesen(firma, "b.csv", csv, inhaber).neu == 2  # zwei gleiche Zahlungen bleiben zwei
    assert zahlungen.einlesen(firma, "b.csv", csv, inhaber).neu == 0
    assert Protokolleintrag.objects.filter(ereignis="kontoauszug.hochgeladen").count() == 4


# ------------------------------------------------------------------ Vorschläge (K7)


def test_nummer_im_text():
    assert nummer_im_text("RE-2026-0412", "Rechnung RE 2026 0412 vielen Dank")
    assert nummer_im_text("RE-2026-0500", "Rechnung 2026/0500")
    assert nummer_im_text("2024-117", "RG 2024-117")
    assert not nummer_im_text("RE-2026-01", "RE-2026-012")
    assert not nummer_im_text("117", "Kunde 1170")
    assert not nummer_im_text("RE1001", "RE10012")


def test_vorschlaege(firma, inhaber, posten):
    huber = posten("RE-2026-0412", "Huber Hausverwaltung GmbH", "1642.00")
    bau = posten("RE-2026-0500", "Bau AG", "1190.00")
    dach = posten("RE-2026-0510", "Dach KG", "500.00")
    posten("RE-2026-0412X", "Huber Hausverwaltung GmbH", "1642.00", quelle="lexware")  # aus Lexware: nie
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    z = {x.zahler: x for x in Zahlung.objects.all()}
    assert z["Huber Hausverwaltung GmbH"].vorschlag == huber
    assert z["Huber Hausverwaltung GmbH"].vorschlag_grund == "Rechnungsnummer und Betrag passen."
    assert z["Bau AG"].vorschlag == bau and "Teilzahlung, danach noch 190.00 €" in z["Bau AG"].vorschlag_grund
    assert z["Dach KG"].vorschlag == dach and "Betrag und Name passen" in z["Dach KG"].vorschlag_grund
    # nichts gebucht, bevor ein Mensch bestätigt
    assert all(b.status == "ueberfaellig" for b in Beleg.objects.all())


def test_spaetere_rechnungskopie_bekommt_den_vorschlag(firma, inhaber):
    from quellen import kopien

    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    huber = Zahlung.objects.get(zahler="Huber Hausverwaltung GmbH")
    assert huber.vorschlag is None and "Keine passende" in huber.vorschlag_grund
    kopie = kopien.einlesen(firma, "re.xml", datei("xrechnung_cii.xml"))
    huber.refresh_from_db()
    assert huber.vorschlag == kopie.beleg and huber.vorschlag_grund == "Rechnungsnummer und Betrag passen."


# ------------------------------------------------------------------ Entscheidung (K7)


def test_bestaetigen_teilzahlung_andere_rechnung_ignorieren(client_inhaber, firma, inhaber, posten):
    huber = posten("RE-2026-0412", "Huber Hausverwaltung GmbH", "1642.00")
    bau = posten("RE-2026-0500", "Bau AG", "1190.00")
    andere = posten("RE-2026-0499", "Bau AG", "2000.00")
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    z = {x.zahler: x for x in Zahlung.objects.all()}
    url = lambda x: reverse("quellen:zahlung", args=[x.pk])  # noqa: E731

    antwort = client_inhaber.post(url(z["Huber Hausverwaltung GmbH"]), {"aktion": "bestaetigen"}, follow=True)
    assert "Rechnung RE-2026-0412 zugeordnet, jetzt bezahlt" in antwort.content.decode()
    huber.refresh_from_db()
    assert (huber.status, huber.offen, huber.bezahlt_am) == ("bezahlt", D("0.00"), date(2026, 11, 4))

    client_inhaber.post(url(z["Bau AG"]), {"aktion": "zuordnen", "beleg": andere.pk})
    andere.refresh_from_db()
    bau.refresh_from_db()
    assert andere.offen == D("1000.00") and andere.status == "ueberfaellig" and bau.offen == D("1190.00")
    eintrag = Protokolleintrag.objects.filter(ereignis="zahlung.zugeordnet").latest("pk")
    assert eintrag.nutzer == inhaber and eintrag.daten["wie_vorgeschlagen"] is False

    client_inhaber.post(url(z["Dach KG"]), {"aktion": "ignorieren"})
    assert Zahlung.objects.get(zahler="Dach KG").status == "ignoriert"
    assert Protokolleintrag.objects.filter(ereignis="zahlung.ignoriert", nutzer=inhaber).exists()

    # schon erledigt: kein zweites Buchen
    antwort = client_inhaber.post(url(z["Huber Hausverwaltung GmbH"]), {"aktion": "bestaetigen"}, follow=True)
    assert "schon erledigt" in antwort.content.decode()


def test_keine_fremden_oder_lexware_rechnungen(client_inhaber, firma, andere_firma, inhaber, posten):
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    zahlung = Zahlung.objects.get(zahler="Bau AG")
    fremd = Beleg.objects.create(firma=andere_firma, extern_id="f1", nummer="F1", offen=D("1000"), status="offen")
    lexware = posten("RE-L-1", "Bau AG", "1000.00", quelle="lexware")
    for beleg in (fremd, lexware):
        antwort = client_inhaber.post(
            reverse("quellen:zahlung", args=[zahlung.pk]), {"aktion": "zuordnen", "beleg": beleg.pk}, follow=True
        )
        assert "Bitte eine offene Rechnung auswählen" in antwort.content.decode()
    with pytest.raises(zahlungen.ZahlungFehler, match="aus Lexware"):
        zahlungen.bestaetigen(zahlung, lexware, inhaber)
    fremd.refresh_from_db()
    assert fremd.offen == D("1000.00") and Zahlung.objects.get(pk=zahlung.pk).status == "neu"


def test_seite_und_hochladen(client_inhaber, firma, posten):
    posten("RE-2026-0412", "Huber Hausverwaltung GmbH", "1642.00")
    seite = client_inhaber.get(reverse("quellen:uebersicht")).content.decode()
    assert "Noch kein Kontoauszug hochgeladen" in seite
    from django.core.files.uploadedfile import SimpleUploadedFile

    antwort = client_inhaber.post(
        reverse("quellen:kontoauszug"),
        {"datei": SimpleUploadedFile("umsaetze.csv", datei("sparkasse.csv"), "text/csv")},
        follow=True,
    )
    seite = antwort.content.decode()
    assert "Kontoauszug mit Stand 05.11.2026 gelesen: 1 Zahlungseingänge, davon 1 neu." in seite
    assert "Vorschlag:" in seite and "RE-2026-0412" in seite and "Huber Hausverwaltung GmbH" in seite
    assert "Letzter Kontoauszug mit Stand 05.11.2026 (heute). 1 Zahlung(en) noch nicht zugeordnet." in seite
    assert 'style="' not in seite
    falsch = client_inhaber.post(
        reverse("quellen:kontoauszug"), {"datei": SimpleUploadedFile("x.csv", b"a;b\n1;2\n")}, follow=True
    )
    assert "Buchungstag und Betrag" in falsch.content.decode()


def test_mitarbeiter_duerfen_nicht(client_mitarbeiter, firma, inhaber):
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)
    z = Zahlung.objects.first()
    assert client_mitarbeiter.post(reverse("quellen:kontoauszug")).status_code == 403
    assert client_mitarbeiter.post(reverse("quellen:zahlung", args=[z.pk]), {"aktion": "ignorieren"}).status_code == 403
    assert Zahlung.objects.filter(status="neu").count() == 3


# ------------------------------------------------------------------ Mahnfreigabe und Versand (K8)


def _vorschlag(firma, beleg):
    from dunning.vorschlaege import vorschlagslauf

    return next(v for v in vorschlagslauf(firma).neu if v.beleg == beleg)


def test_freigabe_zeigt_stand_des_kontoauszugs(client_inhaber, firma, inhaber, posten):
    beleg = posten("RE-2026-0412", "Huber Hausverwaltung GmbH", "1642.00")
    _vorschlag(firma, beleg)
    seite = client_inhaber.get(reverse("dunning:freigabe")).content.decode()
    assert "Rechnungen ohne Lexware: Noch kein Kontoauszug hochgeladen." in seite
    Kontoauszug.objects.create(firma=firma, dateiname="alt.xml", format="camt053", bis=date(2026, 11, 2))
    seite = client_inhaber.get(reverse("dunning:freigabe")).content.decode()
    assert "Stand 02.11.2026 (vor 3 Tagen). Bitte vor der Freigabe einen aktuellen Kontoauszug hochladen." in seite
    Kontoauszug.objects.create(firma=firma, dateiname="neu.xml", format="camt053", bis=date(2026, 11, 4))
    seite = client_inhaber.get(reverse("dunning:freigabe")).content.decode()
    assert "Stand 04.11.2026 (gestern)." in seite and "aktuellen Kontoauszug hochladen" not in seite


def test_kein_versand_solange_eine_passende_zahlung_offen_ist(firma, inhaber, posten, worker):
    from dunning.freigabe import freigeben
    from tests.conftest import alle_jobs_ausfuehren

    firma.email_absender, firma.reply_to = "Malerbetrieb Muster", "buero@muster.example"
    firma.save()
    beleg = posten("RE-2026-0412", "Huber Hausverwaltung GmbH", "1642.00")
    vorschlag = _vorschlag(firma, beleg)
    zahlungen.einlesen(firma, "a.xml", datei("camt053.xml"), inhaber)  # Zahlung da, aber noch nicht bestätigt
    freigeben(firma, inhaber, [vorschlag.pk])
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "vorgeschlagen" and mail.outbox == []
    assert "Am 04.11.2026 sind 1642.00 € eingegangen" in vorschlag.hinweise[0]
    assert Protokolleintrag.objects.filter(ereignis="mahnung.frischecheck_zahlung").exists()
    # nach dem Bestätigen ist der Posten bezahlt und der Vorschlag fällt beim nächsten Lauf weg
    zahlungen.bestaetigen(Zahlung.objects.get(vorschlag=beleg), beleg, inhaber)
    from dunning.vorschlaege import vorschlagslauf

    vorschlagslauf(firma)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "verworfen"
