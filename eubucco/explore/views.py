"""Interactive visualizations, all backed by pre-generated PMTiles served
directly from MinIO. No models — purely view + template + client-side rendering.
"""

from django.shortcuts import render
from django.templatetags.static import static

from eubucco.data import storage


def map(request):
    """Building explorer (2D/3D) backed by ``buildings.pmtiles``."""
    return render(
        request, "explore/map.html", {"pmtiles_url": storage.pmtiles_url("buildings")}
    )


def coverage(request):
    """Regional coverage and quality choropleth backed by ``coverage-stats.pmtiles``."""
    return render(
        request,
        "explore/coverage.html",
        {
            "pmtiles_url": storage.pmtiles_url("coverage"),
            "summary_url": storage.coverage_summary_url(),
            "nuts_names_url": static("metadata/nuts_names.json"),
        },
    )


def conflation(request):
    """Walkthrough of the building conflation/enrichment pipeline on the static
    sample-erfurt dataset (served from eubucco/static/conflation/)."""
    return render(request, "explore/conflation.html")
