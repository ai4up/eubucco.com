import os

from django.shortcuts import render
from django.views.decorators.cache import cache_page


@cache_page(60 * 60)
def getting_started(request):
    # Rendered from eubucco/static/notebooks/getting-started.ipynb via
    # scripts/render_tutorial_notebook.py into a theme-adaptive page
    # (no iframe, single file for both light/dark).
    return render(request, "pages/tutorial-getting-started.html")


def _buildings_pmtiles_url() -> str:
    # Same construction as the explorer view, so it works in local and prod.
    minio_public = os.getenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000").rstrip("/")
    bucket = os.getenv("MINIO_BUCKET", "eubucco")
    version = os.getenv("BUILDINGS_VERSION", "v0.2")
    return f"{minio_public}/{bucket}/{version}/buildings/tiles/buildings.pmtiles"


@cache_page(60 * 60)
def embed_city3d(request):
    """Self-contained 3D city scene embedded (lazy-loaded) in the getting-started page."""
    return render(request, "tutorials/embed/city3d.html", {"pmtiles_url": _buildings_pmtiles_url()})
