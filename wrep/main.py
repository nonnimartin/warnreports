from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import click
import uvicorn
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
        from .backends import orm
        orm.migrate()
    utils.build_css()
    app.mount('/static/scss', StaticFiles(directory=settings.CSS_BUILD_DIR))
    app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')
    yield

app = FastAPI(
    lifespan=lifespan,
    title='warnreports API',
    docs_url='/api/docs/swagger',
    redoc_url='/api/docs/redoc')

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
async def api_home(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'docs/rapidoc.jinja')

@router.get('/about')
async def about(req: Request) -> HTMLResponse:
    stats = await search.search_stats()
    states = await search.search(StateDetail)
    naics = await search.search(NaicsDetail, dict(reports_count_min=1))
    naics = rollup_naics(naics)
    context = dict(stats=stats, states=states, naics=naics)
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

app.include_router(router, include_in_schema=False)
app.include_router(api.router, prefix='/api/v0')
app.include_router(feed.router, prefix='/feed', include_in_schema=False)
app.include_router(dt.router, prefix='/dt', include_in_schema=False)

def cmd(*args, **kw):
    logger.info(f'Starting uvicorn')
    return uvicorn.main.callback('wrep.main:app', *args, **kw)

def rollup_naics(naics: list[NaicsDetail]) -> list[NaicsDetail]:
    counts = defaultdict(int)
    roots: dict[int, NaicsDetail] = {}
    for naic in naics:
        counts[naic.root] += naic.reports_count
        if naic.root == naic.id:
            roots[naic.id] = naic
    for root, naic in roots.items():
        naic.reports_count = counts[root]
    return list(roots.values())

main = click.Command(
    name='main',
    callback=cmd,
    params=uvicorn.main.params[1:],
    context_settings=uvicorn.main.context_settings)

if __name__ == '__main__':
    main()
