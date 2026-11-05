from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("", views.posten, name="posten"),
    path("kunden/", views.kunden, name="kunden"),
    path("kunden/<int:pk>/", views.kunde, name="kunde"),
    path("kunden/kundentyp/", views.kundentyp, name="kundentyp"),
    path("kunden/<int:pk>/kundentyp/", views.kundentyp_setzen, name="kundentyp_setzen"),
    path("kunden/<int:pk>/pause/", views.kontakt_pause, name="kontakt_pause"),
    path("<int:pk>/", views.beleg, name="beleg"),
    path("<int:pk>/pause/", views.beleg_pause, name="beleg_pause"),
    path("<int:pk>/verzugshinweis/", views.beleg_verzugshinweis, name="beleg_verzugshinweis"),
]
