"""Download UI for the EUBUCCO data lake.

Everything is served from MinIO via direct public URLs. The per-region building
table is populated client-side from the FastAPI ``datalake`` API (see
``static/js/download.js``); the additional-files table is server-rendered here by
listing the ``{version}/additional/`` prefix and annotating it with descriptions
from ``{version}/additional/metadata.json``.
"""

import json
import logging
import os

from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import cache_page

from . import storage
from .constants import ADDITIONAL_METADATA_NAME, DATASET_PREFIX

logger = logging.getLogger(__name__)

AVAILABLE_VERSIONS = ["v0.2", "v0.1"]
DEFAULT_VERSION = "v0.2"


def download(request):
    return redirect("data:download_version", version=DEFAULT_VERSION)


def _additional_files(version):
    """List the additional files for a version with public URLs + descriptions."""
    metadata = {}
    raw = storage.read_text(storage.additional_metadata_key(version))
    if raw:
        try:
            metadata = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Could not parse additional metadata.json for %s", version)

    files = []
    for obj in storage.list_prefix(storage.additional_prefix(version)):
        name = obj.object_name.rsplit("/", 1)[-1]
        if not name or name == ADDITIONAL_METADATA_NAME:
            continue
        files.append(
            {
                "name": name,
                "download_link": storage.public_object_url(obj.object_name),
                "size_in_mb": obj.size / 1_000_000,
                "info": metadata.get(name, {}).get("description", ""),
            }
        )
    return sorted(files, key=lambda f: f["size_in_mb"], reverse=True)


def _legacy_building_files(version):
    """Country-level buildings (v0.1) grouped by region with public GPKG/CSV links.

    Object layout: ``{version}/buildings/{gpkg|csv}/{region}.{ext}``. v0.2 is
    NUTS-partitioned and rendered client-side instead (see static/js/download.js).
    """
    groups: dict = {}
    for obj in storage.list_prefix(f"{version}/{DATASET_PREFIX}/"):
        parts = obj.object_name.split("/")
        if len(parts) < 4:
            continue
        fmt, filename = parts[2], parts[-1]
        region = filename.split(".")[0]
        entry = groups.setdefault(region, {"region": region})
        url = storage.public_object_url(obj.object_name)
        size = obj.size / 1_000_000
        if fmt == "gpkg":
            entry["gpkg_link"], entry["gpkg_size"] = url, size
        elif fmt == "csv":
            entry["csv_link"], entry["csv_size"] = url, size
    return sorted(groups.values(), key=lambda x: x["region"])


@cache_page(60 * 60)
def download_version(request, version):
    if version not in AVAILABLE_VERSIONS:
        raise Http404("Unknown version")

    api_url = os.environ.get("API_URL")
    context = {
        "API_URL": api_url,
        "nuts_pm_tiles_url": storage.public_object_url(
            os.environ.get("NUTS_PM_TILES_OBJECT", "nuts.pmtiles")
        ),
        "version": version,
        "available_versions": AVAILABLE_VERSIONS,
        "additional_files": _additional_files(version),
        "countries_api_link": f"{api_url}countries",
    }
    # v0.2 building table is client-side (datalake API); v0.1 is server-rendered.
    if version == "v0.1":
        context["building_files"] = _legacy_building_files(version)
    return render(request, f"data/download_{version}.html", context)
