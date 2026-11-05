from django.apps import AppConfig


class CaptureConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "capture"
    verbose_name = "Erfassung"

    def ready(self) -> None:
        from . import checks  # noqa: F401  # registriert die EU-Systemchecks
