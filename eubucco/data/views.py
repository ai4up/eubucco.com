import os

from django.shortcuts import render
from django.views.decorators.cache import cache_page

from eubucco.api.v0_1.files import FileInfoResponse
from eubucco.files.models import File


@cache_page(60 * 60)
def index(request):
    files = [FileInfoResponse.from_orm(e) for e in File.objects.all()]
    examples = {}
    additional_files = []
    for file in files:
        if file.type == "EX":
            city = file.name.split("-")[-1].split(".")[0]
            if file.name.endswith(".csv.zip"):
                examples[city] = examples.get(city, {}) | {
                    "csv_link": file.download_link,
                    "csv_size_in_mb": file.size_in_mb,
                    "city": city,
                }
            else:
                examples[city] = examples.get(city, {}) | {
                    "gpkg_link": file.download_link,
                    "gpkg_size_in_mb": file.size_in_mb,
                    "city": city,
                }
        if file.type == "AD":
            additional_files.append(file)

    examples = sorted(list(examples.values()), key=lambda d: d["city"])

    context = {
        "API_URL": os.environ.get("API_URL"),
        "examples": examples,
        "additional_files": additional_files,
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
