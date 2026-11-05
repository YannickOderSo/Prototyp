from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.urls import path, reverse_lazy

from . import views, views_zweifaktor

app_name = "accounts"

_passwort = {
    "vergessen": login_not_required(
        views.PasswortVergessen.as_view(
            template_name="accounts/passwort_vergessen.html",
            email_template_name="accounts/mail_passwort_reset.txt",
            subject_template_name="accounts/mail_passwort_reset_betreff.txt",
            success_url=reverse_lazy("accounts:passwort_gesendet"),
        )
    ),
    "gesendet": login_not_required(
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/passwort_gesendet.html")
    ),
    "neu": login_not_required(
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/passwort_neu.html", success_url=reverse_lazy("accounts:passwort_fertig")
        )
    ),
    "fertig": login_not_required(
        auth_views.PasswordResetCompleteView.as_view(template_name="accounts/passwort_fertig.html")
    ),
}

urlpatterns = [
    path("anmelden/", views.anmelden, name="login"),
    path("abmelden/", views.abmelden, name="logout"),
    path("registrieren/", views.registrierung, name="registrieren"),
    path("zwei-faktor/einrichten/", views_zweifaktor.einrichten, name="zweiter_faktor_einrichten"),
    path("zwei-faktor/", views_zweifaktor.pruefen, name="zweiter_faktor"),
    path("zwei-faktor/codes/", views_zweifaktor.wiederherstellungscodes, name="wiederherstellungscodes"),
    path("sicherheit/", views_zweifaktor.sicherheit, name="sicherheit"),
    path("firma-wechseln/", views.firma_wechseln, name="firma_wechseln"),
    path("team/", views.team, name="team"),
    path("einladung/<str:token>/", views.team_annehmen, name="team_annehmen"),
    path("passwort/vergessen/", _passwort["vergessen"], name="passwort_vergessen"),
    path("passwort/gesendet/", _passwort["gesendet"], name="passwort_gesendet"),
    path("passwort/neu/<uidb64>/<token>/", _passwort["neu"], name="password_reset_confirm"),
    path("passwort/fertig/", _passwort["fertig"], name="passwort_fertig"),
]
