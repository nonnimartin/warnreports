from __future__ import annotations

import functools
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from email.utils import formatdate
from uuid import UUID

from fastapi import APIRouter, FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import settings, utils
from ..routers.common import FeedSearchParams, site_absurl

logger = logging.getLogger(__name__)
router = APIRouter()

def default_handler(route: str, path: str|None):
    path = path or route
    async def handler() -> HTMLResponse:
        return frontend_response(path)
    return handler

handlers = {
    route: router.head(route)(router.get(route)(default_handler(route, path)))
    for route, path in dict.items({
        '/': '/index',
        '/search': None,
        '/api': None,
        '/api/docs': None,
        '/about': None})}

@router.head('/r/{id}')
@router.get('/r/{id}')
async def report_view(id: UUID) -> HTMLResponse:
    return frontend_response('/report')

@router.head('/feed')
@router.get('/feed')
async def feed_builder(params: FeedSearchParams) -> HTMLResponse:
    return frontend_response('/feed')

@router.head('/v/{id}')
@router.get('/v/{id}')
async def artifact_view(id: UUID) -> RedirectResponse:
    return artifact_redirect(id, 'inline')

@router.head('/d/{id}')
@router.get('/d/{id}')
async def artifact_download(id: UUID) -> RedirectResponse:
    return artifact_redirect(id, 'download')

@router.head('/openapi.json')
@router.get('/openapi.json')
async def openapi_redirect() -> RedirectResponse:
    url = site_absurl('/api/v0/openapi.json')
    return RedirectResponse(url, status.HTTP_308_PERMANENT_REDIRECT)

def artifact_redirect(id: UUID, disposition: str) -> RedirectResponse:
    path = f'/api/v0/artifacts/{id}/data'
    url = site_absurl(path=path).include_query_params(disposition=disposition)
    return RedirectResponse(url, status.HTTP_308_PERMANENT_REDIRECT)

def frontend_response(path: str) -> HTMLResponse:
    content, headers = read_html(path)
    return HTMLResponse(content, headers=headers)

def read_html(path: str) -> tuple[str, dict[str, str]]:
    path = path.lstrip('/')
    if settings.FRONTEND_CACHE_HTML:
        return read_html_cached(path)
    return read_html_uncached(path)

def read_html_uncached(path: str) -> tuple[str, dict[str, str]]:
    path = path.lstrip('/')
    file = settings.FRONTEND_DIST/'html'/f'{path}.html'
    return file.read_text(), get_stat_headers(file.stat())

read_html_cached = functools.cache(read_html_uncached)

def get_stat_headers(stat: os.stat_result) -> dict[str, str]:
    etag_base = f'{stat.st_mtime}-{stat.st_size}'
    digest = hashlib.md5(etag_base.encode(), usedforsecurity=False).hexdigest()
    return {
        'content-length': str(stat.st_size),
        'last-modified': formatdate(stat.st_mtime, usegmt=True),
        'etag': f'"{digest}"'}


@asynccontextmanager
async def lifespan(app: FastAPI):
    utils.init_logging()
    if settings.FRONTEND_AUTO_BUILD:
        await frontend_build()
    read_html_cached.cache_clear()
    assets = StaticFiles(directory=settings.FRONTEND_DIST/'assets', check_dir=False)
    app.mount('/assets', assets, name='assets')
    yield
    read_html_cached.cache_clear()

from .build import frontend_build
