"""M2-05: Versand-Job mit Frische-Check (D9), Lexware-Mahnungsentwurf und PDF (B6), Mail mit Anhang (D7)."""

import json
from decimal import Decimal

import pytest
from django.core import mail
from django.urls import reverse

from audit.models import Protokolleintrag
from dunning.freigabe import freigeben
from dunning.models import Mahnvorschlag, Versand
from dunning.vorschlaege import vorschlagslauf
from jobs.models import Job
from tests.conftest import alle_jobs_ausfuehren
from tests.dunning.conftest import versendet
from tests.lexware_mock import BASIS, lade, pdf

pytestmark = pytest.mark.django_db
D = Decimal


@pytest.fixture
def umgebung(firma, verbindung, inhaber, lexware_api, ohne_warten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.save()
    return lexware_api


def _zahlung(api, extern_id, offen, status="open"):
    api.get(f"{BASIS}/v1/payments/{extern_id}").respond(
        200,
        json={
            "openAmount": float(offen),
            "currency": "EUR",
            "voucherType": "invoice",
            "voucherStatus": status,
            "paymentItems": [],
        },
    )


def _freigeben_und_senden(firma, inhaber, vorschlag, worker):
    freigeben(firma, inhaber, [vorschlag.pk])
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    return vorschlag


def test_erinnerung_mit_rechnungs_pdf(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=10)
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    rechnung = umgebung.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "versendet"
    assert rechnung.called
    assert len(mail.outbox) == 1
    nachricht = mail.outbox[0]
    assert nachricht.to == ["kunde@example.org"]
    assert nachricht.reply_to == ["buero@muster.example"]
    assert nachricht.from_email == "Malerbetrieb Muster <cockpit@localhost>"
    assert nachricht.subject == f"Zahlungserinnerung zu Rechnung {beleg.nummer}"
    name, inhalt, typ = nachricht.attachments[0]
    assert name == f"Rechnung_{beleg.nummer}.pdf" and inhalt.startswith(b"%PDF") and typ == "application/pdf"
    versand = Versand.objects.get(vorschlag=vorschlag)
    assert versand.message_id == nachricht.extra_headers["Message-ID"]
    beleg.refresh_from_db()
    assert beleg.mahnstufe == 1
    eintrag = Protokolleintrag.objects.get(ereignis="mahnung.versendet")
    assert eintrag.nutzer == inhaber
    assert not any("dunnings" in str(c.request.url) for c in umgebung.calls)  # Stufe 0: keine Lexware-Mahnung


def test_mahnung_legt_entwurf_in_lexware_an(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=40, offen="1000.00", extern_id="inv-0001")
    versendet(beleg, 0, tage_her=30)
    _zahlung(umgebung, "inv-0001", "1000.00")
    anlegen = umgebung.post(f"{BASIS}/v1/dunnings").respond(201, json={**lade("created.json"), "id": "mahn-77"})
    datei = umgebung.get(f"{BASIS}/v1/dunnings/mahn-77/file").respond(200, content=pdf())
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "versendet"
    assert vorschlag.lexware_dunning_id == "mahn-77"
    anfrage = anlegen.calls.last.request
    assert anfrage.url.params["precedingSalesVoucherId"] == "inv-0001"
    assert "finalize" not in str(anfrage.url)
    body = json.loads(anfrage.content)
    assert any(p["name"].startswith("Verzugspauschale") for p in body["lineItems"])
    assert datei.called
    assert mail.outbox[0].attachments[0][0] == f"Mahnung_{beleg.nummer}.pdf"
    assert "Gesamtbetrag: 1.048,07 €" in mail.outbox[0].body
    assert Protokolleintrag.objects.filter(ereignis="lexware.mahnungsentwurf_angelegt").exists()
    beleg.refresh_from_db()
    assert beleg.mahnstufe == 2


def test_frische_check_bezahlt_verwirft(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=10)
    _zahlung(umgebung, beleg.extern_id, "0.00", status="paid")
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "verworfen"
    assert "Inzwischen bezahlt" in vorschlag.verworfen_grund
    assert mail.outbox == []
    beleg.refresh_from_db()
    assert beleg.status == "bezahlt" and not beleg.ist_offen


def test_frische_check_teilzahlung_stellt_erneut_zur_freigabe(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=40, offen="1000.00")
    versendet(beleg, 0, tage_her=30)
    _zahlung(umgebung, beleg.extern_id, "400.00")
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "vorgeschlagen"
    assert vorschlag.offen_betrag == D("400.00")
    assert vorschlag.freigegeben_von is None
    assert "erneut freigeben" in vorschlag.hinweise[0]
    assert mail.outbox == []
    assert not any("dunnings" in str(c.request.url) for c in umgebung.calls)


def test_postversand(client_inhaber, firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=10, email="")
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    umgebung.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "post_bereit"
    assert mail.outbox == []
    datei = client_inhaber.get(reverse("dunning:pdf", args=[vorschlag.pk]))
    assert datei["Content-Type"] == "application/pdf"
    assert datei.content.startswith(b"%PDF")
    assert "PDF herunterladen" in client_inhaber.get(reverse("dunning:freigabe")).content.decode()
    client_inhaber.post(reverse("dunning:post_versendet", args=[vorschlag.pk]))
    vorschlag.refresh_from_db()
    assert vorschlag.status == "versendet" and vorschlag.versendet_am is not None
    beleg.refresh_from_db()
    assert beleg.mahnstufe == 1


def test_lexware_nicht_erreichbar_wird_wiederholt_und_dann_sichtbar(
    client_inhaber, firma, inhaber, posten, umgebung, worker
):
    from datetime import timedelta

    import time_machine

    beleg = posten(tage=10)
    umgebung.get(f"{BASIS}/v1/payments/{beleg.extern_id}").respond(503)
    vorschlag = vorschlagslauf(firma).neu[0]
    freigeben(firma, inhaber, [vorschlag.pk])
    with time_machine.travel(timedelta(0), tick=False) as reise:
        for _ in range(5):
            worker.einen_ausfuehren()
            reise.shift(timedelta(hours=2))
    vorschlag.refresh_from_db()
    assert vorschlag.status == "fehler"
    assert "nicht erreichbar" in vorschlag.fehler
    assert Job.objects.get(typ="dunning.versenden").status == "fehler"
    html = client_inhaber.get(reverse("dunning:freigabe")).content.decode()
    assert "Versand fehlgeschlagen" in html and "Erneut versuchen" in html
    # Neuversuch nach Störung
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    umgebung.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())
    client_inhaber.post(reverse("dunning:neuversuch", args=[vorschlag.pk]))
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "versendet"
    assert len(mail.outbox) == 1


def test_lexware_lehnt_mahnung_ab_sofort_sichtbar(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=40, offen="1000.00", extern_id="inv-0001")
    versendet(beleg, 0, tage_her=30)
    _zahlung(umgebung, "inv-0001", "1000.00")
    umgebung.post(f"{BASIS}/v1/dunnings").respond(406, json={"message": "nicht erlaubt"})
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "fehler"
    assert "abgelehnt" in vorschlag.fehler
    assert Job.objects.get(typ="dunning.versenden").versuche == 1


def test_kein_doppelversand(firma, inhaber, posten, umgebung, worker):
    from dunning.versand import versenden

    beleg = posten(tage=10)
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    umgebung.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    versenden(vorschlag)
    Mahnvorschlag.objects.filter(pk=vorschlag.pk).update(status="freigegeben")  # z. B. Absturz nach dem Senden
    vorschlag.refresh_from_db()
    versenden(vorschlag)
    assert len(mail.outbox) == 1
    vorschlag.refresh_from_db()
    assert vorschlag.status == "versendet"


def test_zustellfehler_sichtbar(firma, inhaber, posten, umgebung, worker, monkeypatch):
    import smtplib

    from django.core.mail.backends.locmem import EmailBackend

    beleg = posten(tage=10)
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    umgebung.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())

    def ablehnen(self, nachrichten):
        raise smtplib.SMTPRecipientsRefused({"kunde@example.org": (550, b"unbekannt")})

    monkeypatch.setattr(EmailBackend, "send_messages", ablehnen)
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "fehler"
    assert "Empfängeradresse abgelehnt" in vorschlag.fehler


def test_ohne_verbindung_fehler(firma, inhaber, posten, heute, worker):
    posten(tage=10)
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "fehler"
    assert "Keine aktive Verbindung" in vorschlag.fehler


def test_abschlag_erinnerung_holt_abschlags_pdf(firma, inhaber, posten, umgebung, worker):
    beleg = posten(tage=10, art="abschlag")
    _zahlung(umgebung, beleg.extern_id, "1190.00")
    route = umgebung.get(f"{BASIS}/v1/down-payment-invoices/{beleg.extern_id}/file").respond(200, content=pdf())
    vorschlag = _freigeben_und_senden(firma, inhaber, vorschlagslauf(firma).neu[0], worker)
    assert vorschlag.status == "versendet"
    assert route.called


def test_nur_freigegebene_werden_versendet(firma, posten, umgebung, worker):
    from jobs.queue import enqueue

    vorschlag = vorschlagslauf(firma).neu[0] if posten(tage=10) else None
    enqueue("dunning.versenden", {"vorschlag_id": vorschlag.pk}, firma=firma)
    alle_jobs_ausfuehren(worker)
    vorschlag.refresh_from_db()
    assert vorschlag.status == "vorgeschlagen"
    assert mail.outbox == []
    assert not umgebung.calls
