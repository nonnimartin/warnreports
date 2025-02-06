from __future__ import annotations

import functools
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import settings, utils
from .common import FeedSearchParams

logger = utils.get_logger('frontend')
router = APIRouter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.FRONTEND_AUTO_BUILD:
        from ..frontend import frontend_build
        await frontend_build()
    read_html_cached.cache_clear()
    if settings.FRONTEND_CACHE_HTML:
        logger.info(f'Caching html')
        for path in dict.fromkeys(routes.values()):
            read_html(path)
    app.mount('/assets', StaticFiles(directory=settings.FRONTEND_DIST/'assets'), name='assets')
    yield

routes = {
    '/': '/index',
    '/search': None,
    '/api': None,
    '/api/docs': None,
    '/about': None,
    '/r/{id}': '/report',
    '/feed': None,
}
routes = {k: v or k for k, v in routes.items()}

def read_html_uncached(path: str) -> str:
    path = path.lstrip('/')
    return (settings.FRONTEND_DIST/f'{path}.html').read_text()

read_html_cached = functools.cache(read_html_uncached)

def read_html(path: str) -> str:
    path = path.lstrip('/')
    if settings.FRONTEND_CACHE_HTML:
        return read_html_cached(path)
    return read_html_uncached(path)

def frontend_response(path: str) -> HTMLResponse:
    return HTMLResponse(read_html(path))

def default_handler(key: str):
    path = routes[key]
    @router.get(key)
    async def handler() -> HTMLResponse:
        return frontend_response(path)
    return handler

handlers = {
    key: default_handler(key) for key in (
        '/',
        '/search',
        '/api',
        '/api/docs',
        '/about',
    )}

@router.get('/r/{id}')
async def report_view(id: UUID) -> HTMLResponse:
    return frontend_response('/report')

@router.get('/feed')
async def feed_builder(params: FeedSearchParams) -> HTMLResponse:
    return frontend_response('/feed')
