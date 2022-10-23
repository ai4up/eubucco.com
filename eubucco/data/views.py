import os

from django.shortcuts import render
from django.views.decorators.cache import cache_page

from eubucco.api.v0_1.examples import ExampleResponse
from eubucco.examples.models import Example


@cache_page(60 * 60)
def index(request):
    examples = [
        ExampleResponse.from_orm(e) for e in Example.objects.all().order_by("name")
    ]

    context = {
        "API_URL": os.environ.get("API_URL"),
        "examples": examples,
        "countries_api_link": f'{os.environ.get("API_URL")}countries',
    }
    # if request.user.is_authenticated:
    #     context["api_key"] = request.user.api_key
    #     return render(
    #         request,
    #         "data/index.html",
    #         context,
    #     )
    return render(request, "data/simple_download.html", context)


@cache_page(60 * 60)
def map(request):
    return render(request, "data/map.html", {"tile_url": os.environ["TILE_URL"]})
