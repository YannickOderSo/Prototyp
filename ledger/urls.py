from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("", views.posten, name="posten"),
    path("kunden/", views.kunden, name="kunden"),
    path("kunden/<int:pk>/", views.kunde, name="kunde"),
    path("kunden/kundentyp/", views.kundentyp, name="kundentyp"),
    path("kunden/<int:pk>/kundentyp/", views.kundentyp_setzen, name="kundentyp_setzen"),
]
