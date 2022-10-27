from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

routes = [
    Mount("", app=StaticFiles(directory="site"), name="EUBUCCO Docs"),
]

app = Starlette(routes=routes)
