import os

from django.shortcuts import render
from django.views.decorators.cache import cache_page


@cache_page(60 * 60)
def map(request):
    return render(request, "data/map.html", {"tile_url": os.environ["TILE_URL"]})
