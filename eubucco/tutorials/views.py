from django.shortcuts import render
from django.views.decorators.cache import cache_page


# Create your views here.
@cache_page(60 * 60)
def getting_started(request):
    return render(request, "tutorials/getting_started.html")


@cache_page(60 * 60)
def predicting_age(request):
    return render(request, "tutorials/predicting_age.html")
