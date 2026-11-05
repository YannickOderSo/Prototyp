"""M7-05: Erinnerung an Angebote kurz vor Ablauf, an den Endkunden nur nach Freigabe (ADR-009, I4)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning import angebote, sammelmail
from dunning.models import Angebotserinnerung
from dunning.services import mahnplan_fuer
from ledger.models import Beleg, Kontakt
from tests.conftest import alle_jobs_ausfuehren
from tests.dunning.conftest import HEUTE
from tests.lexware_mock import BASIS, pdf

pytestmark = pytest.mark.django_db


@pytest.fixture
def angebot(firma):
    zaehler = {"n": 0}

    def anlegen(tage_bis_ablauf=5, email="kunde@example.org", status="offen", **extra):
        zaehler["n"] += 1
        n = zaehler["n"]
        kontakt = Kontakt.objects.create(
            firma=firma, extern_id=f"kq{n}", name=f"Kunde {n}", email=email, ist_unternehmen_extern=True
        )
        return Beleg.objects.create(
            firma=firma,
            extern_id=f"q-{n}",
            art="angebot",
            nummer=f"AN-{n}",
            status=status,
            kontakt=kontakt,
            kontakt_name=kontakt.name,
            brutto=Decimal("2380.00"),
            belegdatum=HEUTE - timedelta(days=20),
            gueltig_bis=HEUTE + timedelta(days=tage_bis_ablauf) if tage_bis_ablauf is not None else None,
            **extra,
        )

    return anlegen


@pytest.fixture
def umgebung(firma, verbindung, lexware_api, ohne_warten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.mahn_signatur = "Max Muster"
    firma.save()
    return lexware_api


def test_vorschlaege_nur_im_fenster_und_einmal(firma, angebot, heute):
    passend = angebot(5)
    angebot(7)  # Grenze: noch im Fenster (Standard 7 Tage)
    angebot(8)  # zu früh
    angebot(-1)  # schon abgelaufen
    angebot(3, email="")  # ohne E-Mail
    angebot(3, status="angenommen")
    angebot(None)  # ohne Ablaufdatum
    neu = angebote.vorschlaege_erzeugen(firma)
    assert sorted(e.beleg.nummer for e in neu) == ["AN-1", "AN-2"]
    assert angebote.vorschlaege_erzeugen(firma) == []  # idempotent: je Angebot höchstens eine Erinnerung
    assert Angebotserinnerung.objects.get(beleg=passend).gueltig_bis == passend.gueltig_bis
    assert Protokolleintrag.objects.filter(ereignis="angebot.erinnerungen_vorgeschlagen").count() == 1
    plan = mahnplan_fuer(firma)
    plan.angebot_erinnerung_aktiv = False
    plan.save()
    angebot(2)
    assert angebote.vorschlaege_erzeugen(firma) == []


def _quotation(api, extern_id, status="open", ablauf_tage=5):
    ablauf = (HEUTE + timedelta(days=ablauf_tage)).isoformat()
    return api.get(f"{BASIS}/v1/quotations/{extern_id}").respond(
        200, json={"id": extern_id, "voucherStatus": status, "expirationDate": f"{ablauf}T00:00:00.000+01:00"}
    )


def test_freigabe_und_versand_mit_pdf(firma, inhaber, angebot, umgebung, worker):
    beleg = angebot(5)
    (e,) = angebote.vorschlaege_erzeugen(firma)
    _quotation(umgebung, beleg.extern_id)
    datei = umgebung.get(f"{BASIS}/v1/quotations/{beleg.extern_id}/file").respond(200, content=pdf())
    assert mail.outbox == []  # ohne Freigabe geht nichts hinaus
    ergebnis = angebote.freigeben(firma, inhaber, [e.pk])
    assert ergebnis.freigegeben == [e]
    alle_jobs_ausfuehren(worker)
    e.refresh_from_db()
    assert e.status == "versendet" and e.message_id and e.empfaenger == "kunde@example.org"
    assert datei.called
    nachricht = mail.outbox[0]
    assert nachricht.to == ["kunde@example.org"] and nachricht.reply_to == ["buero@muster.example"]
    assert nachricht.subject == "Unser Angebot AN-1: Haben Sie noch Fragen?"
    assert f"noch bis zum {(HEUTE + timedelta(days=5)):%d.%m.%Y} gültig" in nachricht.body
    assert "Max Muster" in nachricht.body
    name, inhalt, typ = nachricht.attachments[0]
    assert name == "Angebot_AN-1.pdf" and inhalt.startswith(b"%PDF") and typ == "application/pdf"
    for ereignis in ("angebot.erinnerung_freigegeben", "angebot.erinnerung_versendet"):
        assert Protokolleintrag.objects.get(ereignis=ereignis).nutzer == inhaber


@pytest.mark.parametrize(
    ("status", "ablauf", "grund"),
    [("accepted", 5, "angenommen"), ("rejected", 5, "abgelehnt"), ("open", -1, "abgelaufen")],
)
def test_frische_check_verwirft(firma, inhaber, angebot, umgebung, worker, status, ablauf, grund):
    beleg = angebot(5)
    (e,) = angebote.vorschlaege_erzeugen(firma)
    _quotation(umgebung, beleg.extern_id, status=status, ablauf_tage=ablauf)
    angebote.freigeben(firma, inhaber, [e.pk])
    alle_jobs_ausfuehren(worker)
    e.refresh_from_db()
    assert e.status == "verworfen" and grund in e.verworfen_grund
    assert mail.outbox == []
    assert not any("/file" in str(c.request.url) for c in umgebung.calls)
    assert Protokolleintrag.objects.filter(ereignis="angebot.erinnerung_frischecheck").exists()


def test_frische_check_geloescht(firma, inhaber, angebot, umgebung, worker):
    beleg = angebot(5)
    (e,) = angebote.vorschlaege_erzeugen(firma)
    umgebung.get(f"{BASIS}/v1/quotations/{beleg.extern_id}").respond(404)
    angebote.freigeben(firma, inhaber, [e.pk])
    alle_jobs_ausfuehren(worker)
    e.refresh_from_db()
    assert e.status == "verworfen" and "nicht mehr" in e.verworfen_grund and mail.outbox == []


def test_oberflaeche_freigabe_vorschau_verwerfen(client_freigeber, firma, angebot, heute):
    angebot(5)
    angebot(6)
    e1, e2 = angebote.vorschlaege_erzeugen(firma)
    seite = client_freigeber.get(reverse("dunning:freigabe")).content.decode()
    assert "Angebote nachfassen (2)" in seite and "AN-1" in seite
    vorschau = client_freigeber.get(reverse("dunning:angebot_vorschau", args=[e1.pk])).content.decode()
    assert "Unser Angebot AN-1" in vorschau and "Angebot_AN-1.pdf" in vorschau
    client_freigeber.post(reverse("dunning:angebot_verwerfen", args=[e2.pk]))
    e2.refresh_from_db()
    assert e2.status == "verworfen"
    client_freigeber.post(reverse("dunning:angebote_freigeben"), {"erinnerung": [e1.pk]})
    e1.refresh_from_db()
    assert e1.status == "freigegeben"
    # Navigation zählt offene Erinnerungen mit
    angebot(4)
    angebote.vorschlaege_erzeugen(firma)
    assert (
        '<span class="zahl" aria-label="1 offen">1</span>'
        in client_freigeber.get(reverse("web:start")).content.decode()
    )


def test_mitarbeiter_darf_nicht_freigeben(client_mitarbeiter, firma, angebot, heute):
    angebot(5)
    (e,) = angebote.vorschlaege_erzeugen(firma)
    assert client_mitarbeiter.post(reverse("dunning:angebote_freigeben"), {"erinnerung": [e.pk]}).status_code == 403
    e.refresh_from_db()
    assert e.status == "vorgeschlagen"


def test_mahnplan_texte_und_platzhalter(client_inhaber, firma):
    from dunning.forms import MahnplanForm

    plan = mahnplan_fuer(firma)
    daten = {f: getattr(plan, f) for f in MahnplanForm.Meta.fields}
    daten.update({"text_angebot": "Hallo {kunde}, {unbekannt}", "uhrzeit_freigabe": "07:00"})
    form = MahnplanForm({k: v for k, v in daten.items() if v not in (None, False)}, instance=plan)
    assert not form.is_valid() and "{unbekannt}" in str(form.errors["text_angebot"])


def test_sammelmail_nennt_offene_erinnerungen(firma, inhaber, angebot, heute):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    angebot(5)
    angebote.vorschlaege_erzeugen(firma)
    _, text, _ = sammelmail.inhalt(firma, datetime(2026, 11, 9, 7, 0, tzinfo=ZoneInfo("Europe/Berlin")))
    assert "Angebote nachfassen: 1 Erinnerung an Kunden" in text
