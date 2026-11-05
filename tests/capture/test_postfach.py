"""M3-09: Belegpostfach mit Plus-Adressen, Whitelist und DKIM/SPF über Authentication-Results (E2)."""

from email.message import EmailMessage
from pathlib import Path

import pytest
from django.urls import reverse

from audit.models import Protokolleintrag
from capture import postfach as pf
from capture.models import Belegpostfach, Datei, Erfassung, PostfachEingang

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "capture"
pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def einstellungen(settings):
    settings.BELEGPOSTFACH_ADRESSE = "belege@cockpit.example"
    settings.BELEGPOSTFACH_AUTHSERV_ID = "mx.cockpit.example"
    settings.BELEGPOSTFACH_IMAP_HOST = "imap.cockpit.example"


@pytest.fixture
def kasten(firma):
    return Belegpostfach.objects.create(
        firma=firma, token="abc123", absender=["petra.polier@bau-ag.example", "@muster.example"]
    )


def mail(
    an="belege+abc123@cockpit.example",
    von="Petra Polier <petra.polier@bau-ag.example>",
    auth=None,
    anhaenge=(),
    mid="<1@bau-ag.example>",
):
    m = EmailMessage()
    if auth is not None:
        for kopf in auth:
            m["Authentication-Results"] = kopf
    m["From"] = von
    m["To"] = an
    m["Subject"] = "Stunden Neubau Nord"
    m["Message-ID"] = mid
    m.set_content("Bitte die Stunden abrechnen.")
    for name, daten, typ in anhaenge:
        haupt, unter = typ.split("/")
        m.add_attachment(daten, maintype=haupt, subtype=unter, filename=name)
    return bytes(m)


DKIM_OK = ["mx.cockpit.example; dkim=pass header.d=bau-ag.example header.s=s1; spf=fail smtp.mailfrom=boese.example"]


def test_adresse(kasten):
    assert pf.adresse(kasten) == "belege+abc123@cockpit.example"


def test_gueltige_mail_wird_erfassung_mit_anhaengen(kasten, firma):
    roh = mail(
        auth=DKIM_OK,
        anhaenge=[
            ("zeiten.csv", (FIX / "zeiten.csv").read_bytes(), "text/csv"),
            ("zettel.jpg", (FIX / "stundenzettel.jpg").read_bytes(), "image/jpeg"),
        ],
    )
    eingang = pf.verarbeiten(roh)
    assert eingang.ergebnis == "angenommen"
    erfassung = eingang.erfassung
    assert (erfassung.firma, erfassung.kanal, erfassung.absender) == (firma, "mail", "petra.polier@bau-ag.example")
    assert sorted(Datei.objects.filter(erfassung=erfassung).values_list("art", flat=True)) == ["bild", "csv", "mail"]
    # gleiche Message-ID erneut: nichts Neues
    assert pf.verarbeiten(roh).ergebnis == "doppelt"
    assert Erfassung.objects.count() == 1


@pytest.mark.parametrize(
    ("auth", "grund"),
    [
        (None, "Kein Prüfergebnis"),
        (
            ["mx.cockpit.example; dkim=fail header.d=bau-ag.example; spf=softfail smtp.mailfrom=bau-ag.example"],
            "nicht bestanden",
        ),
        # gefälschter Kopf, vom Absender selbst mitgeschickt (fremde authserv-id)
        (
            ["mx.boese.example; dkim=pass header.d=bau-ag.example; spf=pass smtp.mailfrom=bau-ag.example"],
            "Kein Prüfergebnis",
        ),
        # DKIM bestanden, aber für eine fremde Domain (kein Alignment)
        (
            ["mx.cockpit.example; dkim=pass header.d=boese.example; spf=pass smtp.mailfrom=boese.example"],
            "nicht bestanden",
        ),
    ],
)
def test_gefaelschter_absender_wird_verworfen_und_protokolliert(kasten, firma, auth, grund):
    eingang = pf.verarbeiten(mail(auth=auth))
    assert eingang.ergebnis == "abgelehnt"
    assert grund in eingang.grund
    assert not Erfassung.objects.exists()
    eintrag = Protokolleintrag.objects.get(ereignis="belegpostfach.abgelehnt")
    assert eintrag.firma == firma
    assert eintrag.daten["domain"] == "bau-ag.example"


def test_nur_oberster_eigener_kopf_zaehlt(kasten):
    """Ein vom Angreifer weiter unten eingefügter Kopf mit gleicher Kennung ändert nichts am Ergebnis des Servers."""
    auth = [
        "mx.cockpit.example; dkim=fail header.d=bau-ag.example",
        "mx.cockpit.example; dkim=pass header.d=bau-ag.example",
    ]
    assert pf.verarbeiten(mail(auth=auth)).ergebnis == "abgelehnt"


def test_spf_mit_alignment_reicht(kasten):
    auth = ["mx.cockpit.example; dkim=none; spf=pass smtp.mailfrom=bounce@mail.bau-ag.example"]
    assert pf.verarbeiten(mail(auth=auth)).ergebnis == "angenommen"


def test_absender_nicht_in_whitelist(kasten):
    auth = ["mx.cockpit.example; dkim=pass header.d=fremd.example"]
    eingang = pf.verarbeiten(mail(von="x@fremd.example", auth=auth))
    assert eingang.ergebnis == "abgelehnt" and "Whitelist" in eingang.grund


def test_domain_in_whitelist(kasten):
    auth = ["mx.cockpit.example; dkim=pass header.d=muster.example"]
    assert pf.verarbeiten(mail(von="buero@muster.example", auth=auth, mid="<2@m>")).ergebnis == "angenommen"


def test_unbekannte_adresse_und_inaktives_postfach(kasten):
    assert (
        pf.verarbeiten(mail(an="belege+falsch@cockpit.example", auth=DKIM_OK)).grund
        == "Unbekannte oder inaktive Belegadresse"
    )
    kasten.aktiv = False
    kasten.save()
    assert pf.verarbeiten(mail(auth=DKIM_OK, mid="<3@x>")).ergebnis == "abgelehnt"


def test_ohne_konfigurierte_server_kennung_alles_abgelehnt(kasten, settings):
    settings.BELEGPOSTFACH_AUTHSERV_ID = ""
    assert "nicht konfiguriert" in pf.verarbeiten(mail(auth=DKIM_OK)).grund


def test_zu_viele_anhaenge(kasten):
    anhaenge = [(f"n{i}.txt", b"Notiz", "text/plain") for i in range(10)]
    eingang = pf.verarbeiten(mail(auth=DKIM_OK, anhaenge=anhaenge))
    assert eingang.ergebnis == "abgelehnt" and "Zu viele" in eingang.grund


def test_gefaehrlicher_anhang(kasten):
    eingang = pf.verarbeiten(mail(auth=DKIM_OK, anhaenge=[("rechnung.pdf", b"MZ\x90\x00", "application/pdf")]))
    assert eingang.ergebnis == "abgelehnt"
    assert not Erfassung.objects.exists()


def test_firmen_isoliert(kasten, andere_firma):
    Belegpostfach.objects.create(firma=andere_firma, token="zzz999", absender=["petra.polier@bau-ag.example"])
    e1 = pf.verarbeiten(mail(auth=DKIM_OK, mid="<a@x>"))
    e2 = pf.verarbeiten(mail(an="belege+zzz999@cockpit.example", auth=DKIM_OK, mid="<b@x>"))
    assert e1.erfassung.firma == kasten.firma
    assert e2.erfassung.firma == andere_firma


class FakeImap:
    def __init__(self, mails):
        self.mails = {str(i + 1): roh for i, roh in enumerate(mails)}
        self.gesehen = []
        self.abgemeldet = False

    def login(self, benutzer, passwort):
        return "OK", []

    def select(self, ordner):
        return "OK", [b"1"]

    def search(self, charset, kriterium):
        assert kriterium == "UNSEEN"
        return "OK", [" ".join(self.mails).encode()]

    def fetch(self, nummer, teile):
        if self.mails[nummer] is None:
            raise OSError("kaputt")
        return "OK", [(b"1 (RFC822 {1}", self.mails[nummer]), b")"]

    def store(self, nummer, aktion, flagge):
        self.gesehen.append(nummer)
        return "OK", []

    def logout(self):
        self.abgemeldet = True


def test_abruf_per_imap_eine_kaputte_mail_haelt_andere_nicht_auf(kasten, monkeypatch, worker):
    imap = FakeImap([mail(auth=DKIM_OK, mid="<i1@x>"), None, mail(von="x@fremd.example", auth=DKIM_OK, mid="<i3@x>")])
    monkeypatch.setattr(pf, "imap_verbindung", lambda: imap)
    ergebnisse = pf.abrufen()
    assert [e.ergebnis for e in ergebnisse] == ["angenommen", "abgelehnt"]
    assert imap.gesehen == ["1", "2", "3"]
    assert imap.abgemeldet
    assert PostfachEingang.objects.count() == 2


def test_imap_mit_timeout(settings, monkeypatch):
    aufrufe = {}

    def fake(host, port, timeout):
        aufrufe.update(host=host, port=port, timeout=timeout)
        return "verbindung"

    monkeypatch.setattr(pf.imaplib, "IMAP4_SSL", fake)
    pf.imap_verbindung()
    assert aufrufe == {"host": "imap.cockpit.example", "port": 993, "timeout": 30}


def test_ohne_konfiguration_kein_abruf(settings):
    settings.BELEGPOSTFACH_IMAP_HOST = ""
    assert pf.abrufen() == []


def test_mail_erfassung_geht_direkt_in_die_extraktion(kasten, worker, ki):
    from tests.conftest import alle_jobs_ausfuehren
    from tests.ki_fake import antwort, ergebnis

    ki(antwort(ergebnis()))
    eingang = pf.verarbeiten(mail(auth=DKIM_OK))
    alle_jobs_ausfuehren(worker)
    eingang.erfassung.refresh_from_db()
    assert eingang.erfassung.status == "pruefung"
    assert eingang.erfassung.quellen[0]["herkunft"] == "mail"


def test_einstellungsseite(client_inhaber, firma, settings):
    html = client_inhaber.get(reverse("capture:postfach")).content.decode()
    assert "belege+" in html
    client_inhaber.post(
        reverse("capture:postfach"), {"aktiv": "1", "absender": "Petra@Bau-AG.example\n@muster.example\nkein-eintrag"}
    )
    kasten = Belegpostfach.objects.get(firma=firma)
    assert kasten.absender == ["petra@bau-ag.example", "@muster.example"]
    alt = kasten.token
    client_inhaber.post(reverse("capture:postfach"), {"aktion": "neue_adresse"})
    kasten.refresh_from_db()
    assert kasten.token != alt


def test_einstellungsseite_nur_inhaber(client_freigeber):
    assert client_freigeber.get(reverse("capture:postfach")).status_code == 403


def test_zeitplan():
    from jobs.registry import zeitplan_eintraege

    assert any(e.typ == "capture.postfach_abrufen" and e.cron == "*/5 * * * *" for e in zeitplan_eintraege())
