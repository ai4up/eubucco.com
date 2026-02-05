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


def _grouped(files, ftype):
    grouped = {}
    for f in files:
        if f.type != ftype:
            continue

        region = f.name.split("-")[-1].split(".")[0]
        entry = grouped.setdefault(region, {"region": region})

        if f.name.endswith(".csv.zip"):
            entry["csv_link"] = f.download_link
            entry["csv_size"] = f.size_in_mb
        else:
            entry["gpkg_link"] = f.download_link
            entry["gpkg_size"] = f.size_in_mb

    return sorted(grouped.values(), key=lambda x: x["region"])


def _additional(files):
    additional_files = [f for f in files if f.type == "AD"]

    return sorted(additional_files, key=lambda f: f.size_in_mb, reverse=True)


@cache_page(60 * 60)
def data_versioned(request, version):
    if version not in AVAILABLE_VERSIONS:
        raise Http404("Unknown version")

    files = _fetch_files_for_version(version)
    buildings = _grouped(files, "BU")
    examples = _grouped(files, "EX")
    additional = _additional(files)

    context = {
        "API_URL": os.environ.get("API_URL"),
        "nuts_pm_tiles_url": f"{os.environ.get('MINIO_PUBLIC_ENDPOINT')}/{os.environ.get('MINIO_BUCKET')}/{os.environ.get('NUTS_PM_TILES_OBJECT')}",
        "version": version,
        "available_versions": AVAILABLE_VERSIONS,
        "building_files": buildings,
        "examples_files": examples,
        "additional_files": additional,
        "countries_api_link": f'{os.environ.get("API_URL")}countries',
    }

    return render(request, f"data/download_{version}.html", context)
