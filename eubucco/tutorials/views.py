import os

from django.shortcuts import render
from django.views.decorators.cache import cache_page
from django.views.decorators.clickjacking import xframe_options_sameorigin


@cache_page(60 * 60)
def getting_started(request):
    # Rendered from eubucco/static/notebooks/getting-started.ipynb via
    # scripts/render_tutorial_notebook.py into a theme-adaptive page
    # (no iframe, single file for both light/dark).
    endpoint = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000").rstrip("/")
    use_ssl = endpoint.startswith("https://")
    host = endpoint.split("://", 1)[-1]
    return render(request, "pages/tutorial-getting-started.html", {
        # Config for the in-browser DuckDB-WASM "query the data lake live" demo.
        "duckdb_s3_endpoint": host,
        "duckdb_s3_use_ssl": "true" if use_ssl else "false",
        "duckdb_bucket": os.getenv("MINIO_BUCKET", "eubucco"),
        "duckdb_version": os.getenv("BUILDINGS_VERSION", "v0.2"),
    })


def _pmtiles_url(kind: str) -> str:
    # Same construction as the explorer/coverage views, so it works local and prod.
    minio_public = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000").rstrip("/")
    bucket = os.getenv("MINIO_BUCKET", "eubucco")
    version = os.getenv("BUILDINGS_VERSION", "v0.2")
    paths = {
        "buildings": f"{version}/buildings/tiles/buildings.pmtiles",
        "coverage": f"{version}/coverage/coverage-stats.pmtiles",
    }
    return f"{minio_public}/{bucket}/{paths[kind]}"


@xframe_options_sameorigin
@cache_page(60 * 60)
def embed_city3d(request):
    """Self-contained 3D city scene embedded (lazy-loaded) in the getting-started page."""
    return render(request, "tutorials/embed/city3d.html", {"pmtiles_url": _pmtiles_url("buildings")})


@xframe_options_sameorigin
@cache_page(60 * 60)
def embed_sourcemix(request):
    """NUTS choropleth tinted by each region's blend of data sources (gov/MS/OSM)."""
    return render(request, "tutorials/embed/sourcemix.html", {"pmtiles_url": _pmtiles_url("coverage")})
