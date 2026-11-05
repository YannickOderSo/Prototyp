from django.apps import AppConfig


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reports"
    verbose_name = "Berichte"

    def ready(self) -> None:
        from dunning import sammelmail

        from .wochenbericht import abschnitt

        if abschnitt not in sammelmail.ABSCHNITTE:
            sammelmail.ABSCHNITTE.append(abschnitt)  # F1: Bericht geht montags mit der Sammelfreigabe
