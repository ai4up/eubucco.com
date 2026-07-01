from django.conf import settings


def plausible(request):
    """Expose the Plausible domain so base.html can render the pageview script."""
    return {"PLAUSIBLE_DATA_DOMAIN": getattr(settings, "PLAUSIBLE_DATA_DOMAIN", "")}
