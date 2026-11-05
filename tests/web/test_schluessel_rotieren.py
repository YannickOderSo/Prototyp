"""M4-06: Rotation der Verschlüsselungsschlüssel (Betriebshandbuch)."""

import pytest
from cryptography.fernet import Fernet
from django.core.management import CommandError, call_command

from cockpit import krypto
from cockpit.krypto import entschluesseln, verschluesseln
from connectors.models import Verbindung
from dunning.models import SmtpZugang

pytestmark = pytest.mark.django_db


def test_rotation(settings, firma, verbindung, capsys):
    alt = settings.FERNET_KEYS[0]
    SmtpZugang.objects.create(
        firma=firma, host="smtp.example", absender_adresse="a@b.example", passwort_verschluesselt=verschluesseln("pw")
    )
    neu = Fernet.generate_key().decode()
    settings.FERNET_KEYS = [neu, alt]
    krypto._fernet.cache_clear()
    call_command("schluessel_rotieren", "--pruefen")
    assert "2 mit altem Schlüssel" in capsys.readouterr().out
    call_command("schluessel_rotieren")
    assert "2 Geheimnisse neu verschlüsselt" in capsys.readouterr().out
    call_command("schluessel_rotieren", "--pruefen")
    assert "0 mit altem Schlüssel" in capsys.readouterr().out
    # Alten Schlüssel entfernen: alles bleibt lesbar
    settings.FERNET_KEYS = [neu]
    krypto._fernet.cache_clear()
    assert entschluesseln(Verbindung.objects.get(pk=verbindung.pk).schluessel_verschluesselt) == "test-schluessel"
    assert entschluesseln(SmtpZugang.objects.get(firma=firma).passwort_verschluesselt) == "pw"
    settings.FERNET_KEYS = [alt]
    krypto._fernet.cache_clear()


def test_unlesbares_geheimnis_bricht_ab(settings, verbindung):
    settings.FERNET_KEYS = [Fernet.generate_key().decode()]
    krypto._fernet.cache_clear()
    try:
        with pytest.raises(CommandError, match="mit keinem Schlüssel lesbar"):
            call_command("schluessel_rotieren")
    finally:
        krypto._fernet.cache_clear()
