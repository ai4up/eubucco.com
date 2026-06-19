from django.shortcuts import render
from django.views.decorators.cache import cache_page


@cache_page(60 * 60)
def getting_started(request):
    # Rendered from eubucco/static/notebooks/getting-started.ipynb via
    # scripts/render_tutorial_notebook.py into a theme-adaptive page
    # (no iframe, single file for both light/dark).
    return render(request, "pages/tutorial-getting-started.html")
