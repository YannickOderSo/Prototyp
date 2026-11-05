"""Meilenstein-Abnahme M2 (gegen nachgebaute Lexware-Antworten, Mails gegen Mailpit wenn verfügbar):

20 präparierte Rechnungen (Mix Privat/Unternehmer, Teilzahlung, pausiert, bezahlt kurz vor Versand) ergeben exakt
die erwarteten Vorschläge; nach Freigabe gehen die Mails mit korrekten Beträgen hinaus.
Die erwarteten Beträge sind von Hand gerechnet (Kommentare), nicht mit dem Code selbst.
"""

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.test import override_settings

from dunning.freigabe import freigeben
from dunning.models import Mahnplan, Mahnvorschlag
from dunning.vorschlaege import vorschlagslauf
from tests import mailpit
from tests.conftest import alle_jobs_ausfuehren
from tests.dunning.conftest import HEUTE, versendet
from tests.lexware_mock import BASIS, lade, pdf

pytestmark = pytest.mark.django_db
D = Decimal

# Nr: (erwartete Stufe oder None, erwarteter Gesamtbetrag oder None)
ERWARTET = {
    2: (0, D("1190.00")),
    3: (0, D("1190.00")),
    # Unternehmer, Erinnerung vor 15 Tagen (21.10.) → Verzug ab 23.10.; 13 Zinstage zu 10,52 %:
    # 1190 × 0,1052 × 13/365 = 4,4588 → 4,46; + 40 Pauschale
    4: (1, D("1234.46")),
    # Privat ohne Hinweis: Verzug ab Zugang der Erinnerung 22.10.; 14 Tage zu 6,52 %: 2,976 → 2,98
    5: (1, D("1192.98")),
    # Privat mit Hinweis: Fälligkeit 26.09. + 30 = 26.10.; 10 Tage zu 6,52 %: 2,1257 → 2,13
    6: (1, D("1192.13")),
    # Unternehmer 2. Mahnung: Verzug ab 08.10. (Erinnerung 06.10. + 2); 28 Tage zu 10,52 %: 9,6036 → 9,60; Pauschale schon in Stufe 1
    7: (2, D("1199.60")),
    # Teilzahlung: offen 500; 13 Tage zu 10,52 %: 1,8734 → 1,87; + 40
    9: (1, D("541.87")),
    16: (0, D("1190.00")),
    17: (0, D("1190.00")),
    18: (0, D("1190.00")),
    19: (0, D("1190.00")),
}


@pytest.fixture
def zwanzig(firma, verbindung, inhaber, posten, lexware_api, ohne_warten, heute):
    firma.email_absender = "Malerbetrieb Muster"
    firma.reply_to = "buero@muster.example"
    firma.bankverbindung = "IBAN DE12 3456 7890 1234 5678 90"
    firma.save()
    Mahnplan.objects.create(firma=firma)
    b = {}
    b[1] = posten(tage=5)
    b[2] = posten(tage=7)
    b[3] = posten(tage=10, kundentyp="privat")
    b[4] = posten(tage=25)
    versendet(b[4], 0, tage_her=15)
    b[5] = posten(tage=25, kundentyp="privat")
    versendet(b[5], 0, tage_her=15)
    b[6] = posten(tage=40, kundentyp="privat", verzugshinweis_enthalten=True)
    versendet(b[6], 0, tage_her=30)
    b[7] = posten(tage=40)
    versendet(b[7], 0, tage_her=30)
    versendet(b[7], 1, tage_her=12, pauschale="40.00")
    b[8] = posten(tage=25)
    versendet(b[8], 0, tage_her=5)
    b[9] = posten(tage=25, offen="500.00", brutto="1190.00")
    versendet(b[9], 0, tage_her=15)
    b[10] = posten(tage=10, mahnpause_bis=HEUTE + timedelta(days=7))
    b[11] = posten(tage=10)
    b[11].kontakt.mahnpause_bis = HEUTE + timedelta(days=7)
    b[11].kontakt.save()
    b[12] = posten(tage=10, kundentyp="unbekannt")
    b[13] = posten(tage=10, kundentyp=None)
    b[14] = posten(tage=10, status="bezahlt", offen="0.00", brutto="1190.00")
    b[15] = posten(tage=10, art="angebot")
    b[16] = posten(tage=8, art="abschlag")
    b[17] = posten(tage=10, email="")
    b[18] = posten(tage=10)  # wird kurz vor dem Versand bezahlt
    b[19] = posten(faellig_am=None, belegdatum=HEUTE - timedelta(days=30))
    b[20] = posten(tage=80)
    versendet(b[20], 0, tage_her=70)
    versendet(b[20], 1, tage_her=50)
    versendet(b[20], 2, tage_her=30)
    # Lexware: Zahlstatus und PDFs
    for nr, beleg in b.items():
        if nr == 18:
            antwort = {"openAmount": 0.0, "voucherStatus": "paid", "voucherType": "invoice", "paymentItems": []}
        else:
            antwort = {
                "openAmount": float(beleg.offen),
                "voucherStatus": "open",
                "voucherType": "invoice",
                "paymentItems": [],
            }
        lexware_api.get(f"{BASIS}/v1/payments/{beleg.extern_id}").respond(200, json=antwort)
        lexware_api.get(f"{BASIS}/v1/invoices/{beleg.extern_id}/file").respond(200, content=pdf())
        lexware_api.get(f"{BASIS}/v1/down-payment-invoices/{beleg.extern_id}/file").respond(200, content=pdf())
        lexware_api.get(f"{BASIS}/v1/invoices/{beleg.extern_id}").respond(200, json=lade("invoice_0001.json"))
    zaehler = iter(range(1000))
    lexware_api.post(f"{BASIS}/v1/dunnings").mock(
        side_effect=lambda r: __import__("httpx").Response(201, json={"id": f"mahn-{next(zaehler)}"})
    )
    lexware_api.get(url__regex=rf"{BASIS}/v1/dunnings/mahn-\d+/file").respond(200, content=pdf())
    if mailpit.MAILPIT_URL:
        lexware_api.route(url__startswith=mailpit.MAILPIT_URL).pass_through()
    return b


def test_abnahme_m2(firma, inhaber, zwanzig, worker):
    nummer = {beleg.pk: nr for nr, beleg in zwanzig.items()}
    ergebnis = vorschlagslauf(firma)
    tatsaechlich = {nummer[v.beleg_id]: (v.stufe, v.gesamt) for v in ergebnis.neu}
    assert tatsaechlich == ERWARTET
    assert {nummer[b.pk] for b in ergebnis.klaerung} == {12, 13}
    assert Mahnvorschlag.objects.get(beleg=zwanzig[17], status="vorgeschlagen").versandart == "post"
    assert vorschlagslauf(firma).neu == []  # idempotent

    einstellungen = mailpit.smtp_einstellungen() if mailpit.MAILPIT_URL else {}
    if mailpit.MAILPIT_URL:
        mailpit.leeren()
    with override_settings(**einstellungen):
        freigeben(firma, inhaber, [v.pk for v in ergebnis.neu])
        alle_jobs_ausfuehren(worker)

    status = {nummer[v.beleg_id]: v.status for v in Mahnvorschlag.objects.filter(pk__in=[v.pk for v in ergebnis.neu])}
    assert status.pop(18) == "verworfen"  # Frische-Check: inzwischen bezahlt
    assert status.pop(17) == "post_bereit"
    assert set(status.values()) == {"versendet"}

    if mailpit.MAILPIT_URL:
        texte = {m["Subject"]: m["Text"] for m in mailpit.nachrichten()}
        anhaenge = [a["FileName"] for m in mailpit.nachrichten() for a in m["Attachments"]]
    else:
        texte = {m.subject: m.body for m in mail.outbox}
        anhaenge = [a[0] for m in mail.outbox for a in m.attachments]
    assert len(texte) == 9
    assert len(anhaenge) == 9
    for nr, (stufe, gesamt) in ERWARTET.items():
        if nr in (17, 18):
            continue
        beleg = zwanzig[nr]
        betreff = next(s for s in texte if beleg.nummer in s)
        text = texte[betreff]
        betrag = f"{gesamt:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"
        if stufe == 0:
            assert betreff.startswith("Zahlungserinnerung")
            assert f"Offen sind {betrag}" in text
            assert "Zinsen" not in text
        else:
            assert betreff.startswith(f"{stufe}. Mahnung")
            assert f"Gesamtbetrag: {betrag}" in text, (nr, text)
            assert ("Verzugspauschale" in text) == (nr in (4, 9))
            assert re.search(r"bis (zum|spätestens) \d\d\.\d\d\.2026", text)
