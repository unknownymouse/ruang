from django.urls import path

from . import legal_views

app_name = "legal"

urlpatterns = [
    path("terms/", legal_views.terms, name="terms"),
    path("privacy/", legal_views.privacy, name="privacy"),
    path("open-source/", legal_views.open_source, name="open_source"),
]
