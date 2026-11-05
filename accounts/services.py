"""Fachlogik für Konten: Registrierung mit Einladungscode, Team-Einladungen."""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from audit.services import protokolliere
from web.rechtstexte import zustimmungspflichtig

from .codes import code_hash, neuer_code, neues_token, token_hash
from .models import Einladung, Firma, Mitgliedschaft, Nutzer, Rolle, TeamEinladung, Zustimmung


class EinladungUngueltig(Exception):
    pass


def einladung_erstellen(notiz: str = "", gueltig_tage: int | None = 30, erstellt_von: Nutzer | None = None) -> str:
    """Erzeugt einen Einladungscode und gibt ihn einmalig im Klartext zurück."""
    code = neuer_code()
    Einladung.objects.create(
        code_hash=code_hash(code),
        notiz=notiz,
        erstellt_von=erstellt_von,
        gueltig_bis=timezone.now() + timedelta(days=gueltig_tage) if gueltig_tage else None,
    )
    return code


@dataclass
class Registrierung:
    firmenname: str
    name: str
    email: str
    passwort: str
    einladungscode: str


@transaction.atomic
def registrieren(daten: Registrierung) -> tuple[Nutzer, Firma]:
    """Legt Firma, Inhaber-Konto und Mitgliedschaft an und verbraucht den Einladungscode (A1)."""
    einladung = Einladung.objects.select_for_update().filter(code_hash=code_hash(daten.einladungscode)).first()
    jetzt = timezone.now()
    if (
        einladung is None
        or einladung.verwendet_am is not None
        or (einladung.gueltig_bis is not None and einladung.gueltig_bis < jetzt)
    ):
        raise EinladungUngueltig("Der Einladungscode ist ungültig oder wurde bereits verwendet.")
    firma = Firma.objects.create(name=daten.firmenname)
    nutzer = Nutzer.objects.create_user(email=daten.email, password=daten.passwort, name=daten.name)
    Mitgliedschaft.objects.create(nutzer=nutzer, firma=firma, rolle=Rolle.INHABER)
    einladung.verwendet_am = jetzt
    einladung.verwendet_von = firma
    einladung.save(update_fields=["verwendet_am", "verwendet_von"])
    for text in zustimmungspflichtig():
        Zustimmung.objects.create(nutzer=nutzer, dokument=text.slug, version=text.version)
    protokolliere(firma, "konto.registriert", nutzer=nutzer, objekt=firma)
    return nutzer, firma


TEAM_EINLADUNG_TAGE = 7


def team_einladen(firma: Firma, von: Nutzer, email: str, rolle: str) -> TeamEinladung:
    token = neues_token()
    einladung = TeamEinladung.objects.create(
        firma=firma,
        email=email.lower(),
        rolle=rolle,
        token_hash=token_hash(token),
        erstellt_von=von,
        gueltig_bis=timezone.now() + timedelta(days=TEAM_EINLADUNG_TAGE),
    )
    link = settings.BASIS_URL + reverse("accounts:team_annehmen", args=[token])
    send_mail(
        subject=f"Einladung zu Belegfluss von {firma.name}",
        message=(
            f"Guten Tag,\n\n{von.name or von.email} hat Sie zu Belegfluss von {firma.name} eingeladen "
            f"(Rolle: {Rolle(rolle).label}).\n\nZum Annehmen öffnen Sie bitte diesen Link (gültig "
            f"{TEAM_EINLADUNG_TAGE} Tage):\n{link}\n\nSie werden dabei gebeten, ein Passwort und die "
            "Zwei-Faktor-Anmeldung einzurichten.\n"
        ),
        from_email=None,
        recipient_list=[einladung.email],
    )
    protokolliere(firma, "team.eingeladen", nutzer=von, objekt=einladung, daten={"rolle": rolle})
    return einladung


def team_einladung_finden(token: str) -> TeamEinladung | None:
    einladung = TeamEinladung.objects.select_related("firma").filter(token_hash=token_hash(token)).first()
    if einladung is None or einladung.angenommen_am is not None or einladung.gueltig_bis < timezone.now():
        return None
    return einladung


@transaction.atomic
def team_einladung_annehmen(einladung: TeamEinladung, nutzer: Nutzer) -> Mitgliedschaft:
    einladung = TeamEinladung.objects.select_for_update().get(pk=einladung.pk)
    if einladung.angenommen_am is not None:
        raise EinladungUngueltig("Die Einladung wurde bereits angenommen.")
    mitgliedschaft, _ = Mitgliedschaft.objects.get_or_create(
        nutzer=nutzer, firma=einladung.firma, defaults={"rolle": einladung.rolle}
    )
    einladung.angenommen_am = timezone.now()
    einladung.save(update_fields=["angenommen_am"])
    protokolliere(einladung.firma, "team.beigetreten", nutzer=nutzer, objekt=mitgliedschaft)
    return mitgliedschaft
