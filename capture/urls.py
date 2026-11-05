from django.urls import path

from . import views

app_name = "capture"

urlpatterns = [
    path("", views.liste, name="liste"),
    path("neu/", views.neu, name="neu"),
    path("hochladen/", views.hochladen, name="hochladen"),
    path("<int:pk>/", views.detail, name="detail"),
    path("<int:pk>/neuversuch/", views.neuversuch, name="neuversuch"),
]
