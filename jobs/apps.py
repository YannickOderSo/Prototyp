from django.apps import AppConfig


class JobsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "jobs"
    verbose_name = "Jobs"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        # Jede App meldet ihre Jobs und Zeitplan-Einträge in `<app>/aufgaben.py` an
        autodiscover_modules("aufgaben")
