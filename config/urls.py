import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from django.views import defaults as default_views
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView


class DocsRedirectView(RedirectView):
    url = os.environ["DOCS_URL"]


urlpatterns = [
    path(
        "",
        cache_page(60 * 60)(TemplateView.as_view(template_name="pages/home.html")),
        name="home",
    ),
    path("docs", cache_page(60 * 60)(DocsRedirectView.as_view()), name="docs"),
    path("about", TemplateView.as_view(template_name="pages/about.html"), name="about"),
    path(
        "paper",
        cache_page(60 * 60)(
            TemplateView.as_view(template_name="pages/manuscript.html")
        ),
        name="paper",
    ),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("eubucco.users.urls", namespace="users")),
    path("accounts/", include("allauth.urls")),
    # Your stuff: custom urls includes go here
    path("data/", include("eubucco.data.urls")),
    path("blog/", include("eubucco.blog.urls")),
    path("dumps/", include("eubucco.dumps.urls")),
    path("martor/", include("martor.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns
