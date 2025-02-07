from __future__ import annotations

import functools
import hashlib
import os
from contextlib import asynccontextmanager
from email.utils import formatdate
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
    app.mount('/assets', assets, name='assets')
    yield

assets = StaticFiles(directory=settings.FRONTEND_DIST/'assets', check_dir=False)

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
