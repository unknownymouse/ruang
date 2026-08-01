from django.urls import path

from . import provider_views

app_name = "ai_provider_settings"

urlpatterns = [
    path("", provider_views.provider_settings, name="index"),
    path("<uuid:connection_id>/test/", provider_views.test_connection, name="test"),
]
