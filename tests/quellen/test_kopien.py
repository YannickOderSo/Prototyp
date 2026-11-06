"""M9-03: Rechnungskopien per Mail und Hochladen – Posten und Kunden ohne Lexware, Gutschrift, Dubletten,
Prüfung durch Menschen und Mahnwesen auch ohne Lexware-Verbindung (K1, K3, K4, K8, K10)."""

from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from audit.models import Protokolleintrag
from capture import postfach as pf
from capture.models import PostfachEingang
from jobs.models import Job
from ledger.models import Beleg, Kontakt, Kundentyp
from quellen import kopien
from quellen.models import Kopieadresse, Rechnungskopie
from tests.quellen.hilfen import cii, datei, pdf_ohne_xml, zugferd_pdf

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def einstellungen(settings):
    settings.BELEGPOSTFACH_ADRESSE = "belege@cockpit.example"
    settings.BELEGPOSTFACH_AUTHSERV_ID = "mx.cockpit.example"


def _faellig_in(tage: int) -> bytes:
    """CII-Beispiel mit Rechnungs- und Fälligkeitsdatum relativ zu heute."""
    heute = timezone.localdate()
    return cii(
        **{
            "20261020": (heute - timedelta(days=14 - tage)).strftime("%Y%m%d"),
            "20261103": (heute + timedelta(days=tage)).strftime("%Y%m%d"),
        }
    )


def test_xrechnung_wird_posten_mit_neuem_kunden(firma):
    k = kopien.einlesen(firma, "RE-2026-0412.xml", datei("xrechnung_cii.xml"))
    assert k.status == Rechnungskopie.Status.ANGELEGT and k.format == "xrechnung_cii"
    b = k.beleg
    assert (b.quelle, b.nummer, b.brutto, b.offen) == ("kopie", "RE-2026-0412", Decimal("2142.00"), Decimal("1642.00"))
    assert b.faellig_am == date(2026, 11, 3) and b.lokal and not b.importiert
    kunde = b.kontakt
    assert (kunde.name, kunde.email, kunde.kundentyp) == (
        "Huber Hausverwaltung GmbH",
        "rechnung@huber-hv.example",
        Kundentyp.UNBEKANNT,
    )
    assert kunde.extern_id.startswith("lokal-") and "Lindenallee 4" in kunde.adresse and kunde.ist_unternehmen_extern
    assert Protokolleintrag.objects.filter(ereignis="rechnungskopie.posten_angelegt").exists()
    assert Protokolleintrag.objects.filter(ereignis="kontakt.aus_rechnungskopie_angelegt").exists()


def test_vorhandener_kunde_und_dublette(firma):
    vorhanden = Kontakt.objects.create(firma=firma, extern_id="k1", name="Huber HV", email="Rechnung@huber-hv.example")
    erste = kopien.einlesen(firma, "a.xml", datei("xrechnung_ubl.xml"))
    assert erste.beleg.kontakt == vorhanden  # über die E-Mail gefunden, nicht doppelt angelegt
    zweite = kopien.einlesen(firma, "b.pdf", zugferd_pdf(datei("xrechnung_cii.xml")))
    assert zweite.status == Rechnungskopie.Status.DOPPELT and zweite.beleg == erste.beleg
    assert Beleg.objects.filter(nummer="RE-2026-0412").count() == 1


def test_gutschrift_mindert_den_posten(firma):
    rechnung = kopien.einlesen(firma, "r.xml", datei("xrechnung_ubl.xml")).beleg
    gs = kopien.einlesen(firma, "gs.xml", datei("gutschrift_ubl.xml"))
    assert gs.status == Rechnungskopie.Status.ANGELEGT and gs.beleg == rechnung
    rechnung.refresh_from_db()
    assert rechnung.offen == Decimal("1404.00") and rechnung.status in Beleg.OFFENE_STATUS


def test_gutschrift_ohne_rechnung_geht_in_pruefung(firma):
    gs = kopien.einlesen(firma, "gs.xml", datei("gutschrift_ubl.xml"))
    assert gs.status == Rechnungskopie.Status.PRUEFUNG and "keine passende offene Rechnung" in gs.grund
    assert not Beleg.objects.exists()


@pytest.mark.parametrize(
    ("ersetzen", "grund"),
    [
        ({"<ram:InvoiceCurrencyCode>EUR": "<ram:InvoiceCurrencyCode>CHF"}, "nicht in Euro"),
        ({"<ram:Name>Malerbetrieb Muster GmbH": "<ram:Name>Baumarkt Schmidt AG"}, "nicht Ihre Firma"),
        ({"<ram:TypeCode>380": "<ram:TypeCode>384"}, "Rechnungskorrektur"),
        (
            {
                '<ram:DueDateDateTime><udt:DateTimeString format="102">20261103</udt:DateTimeString></ram:DueDateDateTime>': "",
                "Zahlbar innerhalb von 14 Tagen ohne Abzug.": "Danke für Ihren Auftrag.",
            },
            "Fälligkeit",
        ),
    ],
)
def test_unklare_kopien_gehen_in_pruefung(firma, ersetzen, grund):
    inhalt = datei("xrechnung_cii.xml").decode()
    for alt, neu in ersetzen.items():
        inhalt = inhalt.replace(alt, neu)
    k = kopien.einlesen(firma, "x.xml", inhalt.encode())
    assert k.status == Rechnungskopie.Status.PRUEFUNG and grund in k.grund
    assert not Beleg.objects.exists()


def test_unlesbare_dateien(firma):
    assert kopien.einlesen(firma, "x.xml", datei("angriff_dtd.xml")).status == "abgelehnt"
    assert kopien.einlesen(firma, "foto.jpg", b"\xff\xd8\xff").status == "abgelehnt"
    pdf = kopien.einlesen(firma, "scan.pdf", pdf_ohne_xml())
    assert pdf.status == "pruefung" and pdf.format == "pdf" and "keinen lesbaren Text" in pdf.grund
    assert not Job.objects.filter(typ="quellen.ki_lesen").exists()  # ohne Text keine KI


# ------------------------------------------------------------------ Mail an die Kopie-Adresse


def _mail(an: str, von: str = "rechnung@muster.example", auth: bool = True, anhang: bytes | None = None) -> bytes:
    m = EmailMessage()
    if auth:
        m["Authentication-Results"] = "mx.cockpit.example; dkim=pass header.d=muster.example header.s=s1"
    m["From"], m["To"], m["Subject"], m["Message-ID"] = von, an, "Rechnung RE-2026-0412", "<k1@muster.example>"
    m.set_content("Ihre Rechnung im Anhang.")
    if anhang is not None:
        m.add_attachment(anhang, maintype="application", subtype="pdf", filename="RE-2026-0412.pdf")
    return bytes(m)


def test_kopie_per_mail(firma):
    adresse = Kopieadresse.objects.create(firma=firma, token="rabc", absender=["@muster.example"])
    eingang = pf.verarbeiten(_mail("belege+rabc@cockpit.example", anhang=zugferd_pdf(datei("xrechnung_cii.xml"))))
    assert eingang.ergebnis == "kopie" and eingang.firma == firma
    k = Rechnungskopie.objects.get()
    assert (k.weg, k.status, k.message_id) == ("mail", "angelegt", "<k1@muster.example>")
    assert pf.verarbeiten(_mail("belege+rabc@cockpit.example", anhang=b"x")).ergebnis == "doppelt"
    adresse.absender = ["chef@muster.example"]
    adresse.save()
    eingang = pf.verarbeiten(_mail("belege+rabc@cockpit.example", anhang=b"%PDF-").replace(b"<k1@", b"<k2@"))
    assert eingang.ergebnis == "abgelehnt" and "Absender" in eingang.grund
    assert Protokolleintrag.objects.filter(ereignis="rechnungskopie.abgelehnt").exists()


def test_kopie_per_mail_ohne_dkim_oder_ohne_anhang(firma):
    Kopieadresse.objects.create(firma=firma, token="rabc", absender=["@muster.example"])
    ohne_auth = pf.verarbeiten(_mail("belege+rabc@cockpit.example", auth=False, anhang=b"%PDF-"))
    assert ohne_auth.ergebnis == "abgelehnt"
    ohne_anhang = pf.verarbeiten(_mail("belege+rabc@cockpit.example").replace(b"<k1@", b"<k3@"))
    assert ohne_anhang.ergebnis == "abgelehnt" and "Keine Rechnungsdatei" in ohne_anhang.grund
    unbekannt = pf.verarbeiten(_mail("belege+rzzz@cockpit.example", anhang=b"%PDF-").replace(b"<k1@", b"<k4@"))
    assert unbekannt.ergebnis == "abgelehnt" and unbekannt.firma is None
    assert not Rechnungskopie.objects.exists() and PostfachEingang.objects.count() == 3


# ------------------------------------------------------------------ Oberfläche


def test_hochladen_und_pruefen(client_inhaber, firma, inhaber):
    url = reverse("quellen:uebersicht")
    dateien = [
        SimpleUploadedFile("a.xml", datei("xrechnung_cii.xml"), "text/xml"),
        SimpleUploadedFile("b.xml", cii("RE-2026-0500", **{"Malerbetrieb Muster GmbH": "Fremdfirma AG"}), "text/xml"),
    ]
    antwort = client_inhaber.post(url, {"dateien": dateien}, follow=True)
    assert "2 Dateien gelesen: 1 übernommen, 1 zu prüfen." in antwort.content.decode()
    pruefen = Rechnungskopie.objects.get(status="pruefung")
    seite = client_inhaber.get(reverse("quellen:kopie", args=[pruefen.pk])).content.decode()
    assert "Fremdfirma AG" in seite and 'value="RE-2026-0500"' in seite
    werte = {
        "art": "rechnung",
        "nummer": "RE-2026-0500",
        "belegdatum": "2026-10-20",
        "faellig_am": "2026-11-03",
        "kaeufer_name": "Huber Hausverwaltung GmbH",
        "kaeufer_email": "rechnung@huber-hv.example",
        "brutto": "2.142,00",
        "zahlbetrag": "1.642,00",
    }
    ohne_faelligkeit = client_inhaber.post(reverse("quellen:kopie", args=[pruefen.pk]), {**werte, "faellig_am": ""})
    assert "Bitte die Fälligkeit" in ohne_faelligkeit.content.decode()
    client_inhaber.post(reverse("quellen:kopie", args=[pruefen.pk]), {**werte, "aktion": "uebernehmen"})
    pruefen.refresh_from_db()
    assert pruefen.status == "angelegt" and pruefen.geprueft_von == inhaber
    assert pruefen.beleg.offen == Decimal("1642.00")
    # beide Rechnungen gehören zum selben (neu angelegten) Kunden
    assert Kontakt.objects.filter(firma=firma).count() == 1


def test_kopie_adresse_einrichten(client_inhaber, firma):
    client_inhaber.post(reverse("quellen:adresse"))
    adresse = Kopieadresse.objects.get(firma=firma)
    assert adresse.token.startswith("r")
    client_inhaber.post(
        reverse("quellen:adresse"), {"aktion": "speichern", "aktiv": "1", "absender": "Rechnung@Muster.example\nkein"}
    )
    adresse.refresh_from_db()
    assert adresse.absender == ["rechnung@muster.example"]
    seite = client_inhaber.get(reverse("quellen:uebersicht")).content.decode()
    assert f"belege+{adresse.token}@cockpit.example" in seite
    # Cockpit ohne Lexware zeigt keinen Lexware-Hinweis mehr, sondern den Weg über Kopien (K10)
    start = client_inhaber.get(reverse("web:start")).content.decode()
    assert "Noch keine Verbindung zu Lexware" not in start and "Rechnungskopien" in start


def test_nur_inhaber_und_freigeber(client_mitarbeiter):
    assert client_mitarbeiter.get(reverse("quellen:uebersicht")).status_code == 403


# ------------------------------------------------------------------ Mahnwesen ohne Lexware (K8)


def test_vorschlagslauf_auch_ohne_lexware(firma, worker):
    from dunning.models import Mahnvorschlag
    from jobs.queue import enqueue
    from tests.conftest import alle_jobs_ausfuehren

    k = kopien.einlesen(firma, "r.xml", _faellig_in(-12))
    k.beleg.kontakt.kundentyp = Kundentyp.UNTERNEHMER
    k.beleg.kontakt.save()
    enqueue("dunning.vorschlaege_alle", {})
    alle_jobs_ausfuehren(worker)
    vorschlag = Mahnvorschlag.objects.get(beleg=k.beleg)
    assert vorschlag.stufe == 0 and any("Rechnungskopie" in h for h in vorschlag.hinweise)
