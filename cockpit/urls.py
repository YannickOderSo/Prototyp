from django.urls import include, path

urlpatterns = [
    path("konto/", include("accounts.urls")),
    path("einstellungen/verbindung/", include("connectors.urls")),
    path("", include("web.urls")),
]
