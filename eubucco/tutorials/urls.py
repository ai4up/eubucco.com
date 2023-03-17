from django.urls import path

from . import views

app_name = "tutorials"
urlpatterns = [
    path("getting_started", views.getting_started, name="getting_started"),
    path("predicting_age", views.predicting_age, name="predicting_age"),
]
