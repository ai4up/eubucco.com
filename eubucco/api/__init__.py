import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

api = FastAPI(version="0.1", title="eubucco")

if "DEVELOPMENT" in os.environ:
    origins = [
        "http://0.0.0.0:8000",
        "http://localhost",
        "http://localhost:8000",
    ]
    api.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    import sentry_sdk

    origins = ["https://eubucco.com"]
    origins_regex = [r"https://.*\.eubucco\.com"]
    api.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origins_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    sentry_sdk.init(
        dsn="https://a45bad10c1ac4b2aa4a8bdb5c9ec01e9@o4504014824734720.ingest.sentry.io/4504014832271360",
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for performance monitoring.
        # We recommend adjusting this value in production,
        traces_sample_rate=0.1,
    )
