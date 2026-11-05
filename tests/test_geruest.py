"""M0-01: Projekt startet, Apps sind registriert, Einstellungen kommen aus der Umgebung."""

from django.apps import apps
from django.conf import settings
from django.core.management import call_command

APPS = ["accounts", "connectors", "ledger", "dunning", "capture", "reports", "audit", "jobs", "web"]


def test_alle_apps_aus_der_architektur_sind_installiert():
    for name in APPS:
        assert apps.is_installed(name), name


def test_zeitzone_und_sprache():
    assert settings.TIME_ZONE == "Europe/Berlin"
    assert settings.USE_TZ is True
    assert settings.LANGUAGE_CODE == "de"


def test_nutzermodell_mit_email_login():
    assert settings.AUTH_USER_MODEL == "accounts.Nutzer"
    from django.contrib.auth import get_user_model

    assert get_user_model().USERNAME_FIELD == "email"


def test_systemchecks_ohne_fehler():
    call_command("check", "--fail-level", "ERROR")


def test_keine_fehlenden_migrationen(db):
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)
