from django.urls import include, path

from web.gesundheit import healthz

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("konto/", include("accounts.urls")),
    path("einstellungen/verbindung/", include("connectors.urls")),
    path("hooks/", include("connectors.hooks_urls")),
    path("posten/", include("ledger.urls")),
    path("mahnungen/", include("dunning.urls")),
    path("erfassen/", include("capture.urls")),
    path("berichte/", include("reports.urls")),
    path("import/", include("datenimport.urls")),
    path("telefon/", include("telefon.urls")),
    path("", include("web.urls")),
]
