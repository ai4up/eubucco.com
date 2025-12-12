from django.urls import path
from django.shortcuts import redirect

from . import views

app_name = "files"
urlpatterns = [
    path("", lambda r: redirect("files:version", version="v0.2"), name="index"),
    path("<str:version>", views.data_versioned, name="version"),
]
