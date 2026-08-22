"""URL configuration for the preview app."""
from django.urls import path

from . import views

app_name = "preview"

urlpatterns = [
    path("", views.index, name="index"),
]