from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import click
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import search, settings, utils
from .models import *
from .routers import api, dt, feed

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
    return templates.TemplateResponse(req, 'index.jinja')

@router.get('/search')
async def report_search(req: Request) -> HTMLResponse:
    states = await search.search(StateDetail)
    context = dict(states=states)
    return templates.TemplateResponse(req, 'search.jinja', context)

@router.get('/api')
async def api_home(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'api.jinja')

@router.get('/api/docs')
async def api_docs(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'docs/rapidoc.jinja')

@router.get('/about')
async def about(req: Request) -> HTMLResponse:
    stats = search.search_stats()
    states = search.search(StateDetail)
    naics = search.search(NaicsDetail, dict(reports_count_min=1, depth_max=0))
    context = dict(stats=await stats, states=await states, naics=await naics)
    return templates.TemplateResponse(req, 'about.jinja', context)

@router.get('/r/{id}')
async def report_view(req: Request, id: UUID) -> HTMLResponse:
    report = await search.retrieve404(ReportData, id=id)
    context = dict(report=report)
    return templates.TemplateResponse(req, 'report.jinja', context)

@router.get('/d/{id}')
@router.head('/d/{id}')
async def artifact_download(id: UUID) -> FileResponse:
    return await artifact(id, 'download')

@router.get('/v/{id}')
@router.head('/v/{id}')
async def artifact_view(id: UUID) -> FileResponse:
    return await artifact(id, 'inline')

async def artifact(id: UUID, disposition: str) -> FileResponse:
    artifact = await search.retrieve404(ArtifactDetail, id=id)
    return FileResponse(
        Path(settings.ARTIFACTS_DIR, artifact.path),
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type=disposition)


app = FastAPI(
    lifespan=lifespan,
    title='warnreports API',
    docs_url='/api/docs/swagger',
    redoc_url='/api/docs/redoc')
app.include_router(router, include_in_schema=False)
app.include_router(api.router, prefix='/api/v0')
app.include_router(feed.router, prefix='/feed', include_in_schema=False)
app.include_router(dt.router, prefix='/dt', include_in_schema=False)


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
