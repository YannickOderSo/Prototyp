from django.urls import path

from . import webhooks

app_name = "hooks"

urlpatterns = [
    path("lexware/<str:token>/", webhooks.lexware, name="lexware"),
]
