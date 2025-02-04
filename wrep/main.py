from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import click
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, utils
from .models import *
from .routers import api, feed
from .routers.common import FeedSearchParams

logger = utils.get_logger('main')
templates = Jinja2Templates(env=utils.jinja_env())

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DB_AUTO_MIGRATE:
        logger.info(f'Running auto migrate')
        from .migrations import migrate
        migrate()
    if settings.ASSETS_AUTO_BUILD:
        utils.assets_build()
    app.mount('/static/scss', StaticFiles(directory=settings.CSS_BUILD_DIR))
    app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')
    yield

router = APIRouter()

@router.get('/')
async def index(req: Request) -> HTMLResponse:
    return await frontend_response(req, '/index')

@router.get('/search')
async def report_search(req: Request) -> HTMLResponse:
    return await frontend_response(req)

@router.get('/api')
async def api_home(req: Request) -> HTMLResponse:
    return await frontend_response(req)

@router.get('/api/docs')
async def api_docs(req: Request) -> HTMLResponse:
    return await frontend_response(req)

@router.get('/about')
async def about(req: Request) -> HTMLResponse:
    return await frontend_response(req)

@router.get('/r/{id}')
async def report_view(req: Request, id: UUID) -> HTMLResponse:
    return await frontend_response(req, '/report')

@router.get('/feed')
async def feed_builder(req: Request, params: FeedSearchParams) -> HTMLResponse:
    return await frontend_response(req)

@router.get('/d/{id}')
@router.head('/d/{id}')
async def artifact_download(id: UUID) -> FileResponse:
    return await api.artifact_data(id, disposition='download')

@router.get('/v/{id}')
@router.head('/v/{id}')
async def artifact_view(id: UUID) -> FileResponse:
    return await api.artifact_data(id, disposition='inline')


async def frontend_response(req: Request, path: str|None = None) -> HTMLResponse:
    if path is None:
        path = req.url.path
    return templates.TemplateResponse(req, 'frontend.jinja', dict(path=path))

app = FastAPI(
    lifespan=lifespan,
    title='warnreports API',
    docs_url='/api/docs/swagger',
    redoc_url='/api/docs/redoc')
app.include_router(router, include_in_schema=False)
app.include_router(api.router, prefix='/api/v0')
app.include_router(feed.router, prefix='/feed', include_in_schema=False)


if __name__ == '__main__':
    import uvicorn
    def cmd(*args, **kw):
        logger.info(f'Starting uvicorn')
        return uvicorn.main.callback('wrep.main:app', *args, **kw)
    main = click.Command(
        name='main',
        callback=cmd,
        params=uvicorn.main.params[1:],
        context_settings=uvicorn.main.context_settings)
    main()
