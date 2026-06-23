from django.urls import path

from . import views

app_name = "tutorials"
urlpatterns = [
    path("getting_started", views.getting_started, name="getting_started"),
    path("embed/city3d", views.embed_city3d, name="embed_city3d"),
    path("embed/sourcemix", views.embed_sourcemix, name="embed_sourcemix"),
]
