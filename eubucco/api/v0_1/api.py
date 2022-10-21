from fastapi.responses import RedirectResponse

from .. import api
from .countries import router as countries_router
from .examples import router as examples_router

api.include_router(countries_router, prefix="/v0.1/countries", tags=["countries"])
api.include_router(examples_router, prefix="/v0.1/examples", tags=["examples"])


# api.include_router(regions_router, prefix="/regions", tags=["regions"])
# api.include_router(cities_router, prefix="/cities", tags=["cities"])
# api.include_router(buildings_router, prefix="/v0.1/buildings", tags=["buildings v0.1"])
# api.include_router("/dumps", dumps_router, tags=["dumps"])


@api.get("/", tags=["redirect to docs"])
async def redirect_to_docs():
    """
    Redirects to the docs when visiting the root api.
    """
    return RedirectResponse("/docs")
