from fastapi import APIRouter

from . import api as api
from . import artifacts as artifacts
from . import feed as feed

search = APIRouter()
search.include_router(api.router, prefix='/api/v0')
search.include_router(feed.router, prefix='/feed', include_in_schema=False)

backend = APIRouter()
backend.include_router(search)
backend.include_router(artifacts.router, prefix='/api/v0', include_in_schema=False)
