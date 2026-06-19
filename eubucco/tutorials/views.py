from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_page


# Create your views here.
@cache_page(60 * 60)
def getting_started(request):
    # Rendered from getting-started-website.ipynb via scripts/render_tutorial_notebook.py
    # into a theme-adaptive page (no iframe, single file for both light/dark).
    return render(request, "pages/tutorial-getting-started.html")


@cache_page(60 * 60)
def predicting_age(request):
    light_url = static("html/tutorial-predicting-building-age.html")
    dark_url = static("html/tutorial-predicting-building-age-dark-theme.html")
    return render(
        request,
        "tutorials/tutorial.html",
        {"light_url": light_url, "dark_url": dark_url},
    )
