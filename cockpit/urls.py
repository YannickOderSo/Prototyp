from django.urls import include, path

urlpatterns = [
    path("konto/", include("accounts.urls")),
    path("einstellungen/verbindung/", include("connectors.urls")),
    path("hooks/", include("connectors.hooks_urls")),
    path("posten/", include("ledger.urls")),
    path("mahnungen/", include("dunning.urls")),
    path("erfassen/", include("capture.urls")),
    path("", include("web.urls")),
]
