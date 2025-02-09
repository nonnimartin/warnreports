from fastapi import APIRouter
from . import api as api
from . import feed as feed

search = APIRouter()
search.include_router(api.router, prefix='/api/v0')
search.include_router(feed.router, prefix='/feed', include_in_schema=False)

artifacts = APIRouter()
artifacts.include_router(api.artifacts_data, prefix='/api/v0')

backend = APIRouter()
backend.include_router(search)
backend.include_router(artifacts, include_in_schema=False)
