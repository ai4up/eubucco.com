import os

from django.shortcuts import render, Http404
from django.views.decorators.cache import cache_page

from eubucco.api.v1.files import FileInfoResponse
from eubucco.files.models import File

AVAILABLE_VERSIONS = ["v0.2", "v0.1"]
DEFAULT_VERSION = "v0.2"

def _fetch_files_for_version(version):
    return [
        FileInfoResponse.from_orm(f)
        for f in File.objects.filter(version=version)
    ]


def _group_examples(files):
    grouped = {}
    for f in files:
        if f.type != "EX":
            continue

        city = f.name.split("-")[-1].split(".")[0]
        entry = grouped.setdefault(city, {"city": city})

        if f.name.endswith(".csv.zip"):
            entry["csv_link"] = f.download_link
            entry["csv_size_in_mb"] = f.size_in_mb
        else:
            entry["gpkg_link"] = f.download_link
            entry["gpkg_size_in_mb"] = f.size_in_mb

    return sorted(grouped.values(), key=lambda x: x["city"])


def _group_additional(files):
    return [f for f in files if f.type == "AD"]


@cache_page(60 * 60)
def data_versioned(request, version):
    if version not in AVAILABLE_VERSIONS:
        raise Http404("Unknown version")

    files = _fetch_files_for_version(version)
    examples = _group_examples(files)
    additional_files = _group_additional(files)

    context = {
        "API_URL": os.environ.get("API_URL"),
        "NUTS_PM_TILES_URL": os.environ.get("NUTS_PM_TILES_URL", ""),
        "version": version,
        "available_versions": AVAILABLE_VERSIONS,
        "examples": examples,
        "additional_files": additional_files,
        "countries_api_link": f'{os.environ.get("API_URL")}countries',
    }

    return render(request, f"data/download_{version}.html", context)


@cache_page(60 * 60)
def map(request):
    return render(request, "data/map.html", {"tile_url": os.environ["TILE_URL"]})
