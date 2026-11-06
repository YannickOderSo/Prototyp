from django.apps import AppConfig


class QuellenConfig(AppConfig):
    """Rechnungskopien und Kontoauszüge (ADR-011 Stufe 3): Posten und Zahlungen ohne Schnittstelle zum Bestandstool."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "quellen"
    verbose_name = "Rechnungskopien und Kontoauszüge"
