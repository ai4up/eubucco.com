from django.urls import path

from . import views

app_name = "explore"
urlpatterns = [
    path("map", views.map, name="map"),
    path("coverage", views.coverage, name="coverage"),
    path("conflation", views.conflation, name="conflation"),
]
