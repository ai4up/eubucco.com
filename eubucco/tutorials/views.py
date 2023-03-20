from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_page


# Create your views here.
@cache_page(60 * 60)
def getting_started(request):
    light_url = static("html/tutorial-getting-started.html")
    return render(
        request,
        "tutorials/tutorial.html",
        {"light_url": light_url, "dark_url": light_url},
    )


@cache_page(60 * 60)
def predicting_age(request):
    light_url = static("html/tutorial-predicting-building-age.html")
    return render(
        request,
        "tutorials/tutorial.html",
        {"light_url": light_url, "dark_url": light_url},
    )
