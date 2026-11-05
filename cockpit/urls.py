from django.urls import include, path

urlpatterns = [
    path("konto/", include("accounts.urls")),
    path("", include("web.urls")),
]
