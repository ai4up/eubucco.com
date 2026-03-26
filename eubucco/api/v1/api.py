from fastapi.responses import RedirectResponse

from .. import api
from .datalake import router as datalake_router
from .files import router as files_router

api.include_router(files_router, prefix="/v1/files", tags=["files"])
api.include_router(datalake_router, prefix="/v1/datalake", tags=["datalake"])


@api.get("/", tags=["redirect to docs"])
async def redirect_to_docs():
    """
    Redirects to the docs when visiting the root api.
    """
    return RedirectResponse("/docs")
