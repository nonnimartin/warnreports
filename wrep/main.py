from __future__ import annotations

from pathlib import Path
from uuid import UUID

import click
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, utils, search
from .models import *
from .routers import *

logger = utils.get_logger('main')
app = FastAPI(title='WARN Reporter')
static = StaticFiles(directory=settings.STATIC_DIR)
templates = Jinja2Templates(env=utils.jinja_env())

app.include_router(prefix='/api/v0', router=api.router)
app.include_router(prefix='/feed', router=feed.router)
app.mount('/static', static, name='static')

@app.get('/', include_in_schema=False)
async def index(req: Request) -> HTMLResponse:
    stats = await search.search_stats()
    majors = (await search.search(ReportData, dict(employees_gt=49), 10))[0]
    states = (await search.search(StateDetail))[0]
    context = dict(stats=stats, majors=majors, states=states)
    return templates.TemplateResponse(req, 'index.jinja', context)

@app.get('/r/{id}', include_in_schema=False)
async def report_view(req: Request, id: UUID) -> HTMLResponse:
    report = await search.retrieve404(ReportData, id=id)
    context = dict(report=report)
    return templates.TemplateResponse(req, 'report.jinja', context)

@app.get('/d/{id}', include_in_schema=False)
@app.head('/d/{id}', include_in_schema=False)
async def artifact_download(id: UUID) -> FileResponse:
    return await artifact(id, 'download')

@app.get('/v/{id}', include_in_schema=False)
@app.head('/v/{id}', include_in_schema=False)
async def artifact_view(id: UUID) -> FileResponse:
    return await artifact(id, 'inline')

async def artifact(id: UUID, disposition: str) -> FileResponse:
    artifact = await search.retrieve404(ArtifactDetail, id=id)
    path = Path(settings.ARTIFACTS_DIR, artifact.path)
    return FileResponse(
        path,
        media_type=artifact.media_type,
        filename=artifact.name,
        content_disposition_type=disposition)

@app.get('/search', include_in_schema=False)
async def report_search(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'search.jinja')

class ReportDtResult(DataModel):
    data: list[ReportData]
    recordsTotal: int
    recordsFiltered: int
    draw: int

@app.get('/dt/reports', include_in_schema=False, response_model_by_alias=False)
async def search_dt(
    req: Request,
    length: Limit,
    start: Offset,
    draw: int,
) -> ReportDtResult:
    qp = dict(req.query_params)
    order = parse_dt_order(qp)
    params = dict(order=order)
    text = qp.get('search[value]')
    if text:
        params.update(text=text)
    data, total = await search.search(ReportData, params, length, start)
    return ReportDtResult(
        data=data,
        recordsTotal=total,
        recordsFiltered=total,
        draw=draw)

def parse_dt_order(params: dict[str, str]) -> str|None:
    res = []
    for i in range(len(params)):
        try:
            field = params[f'order[{i}][name]']
        except KeyError:
            break
        if params[f'order[{i}][dir]'] == 'desc':
            field = f'-{field}'
        res.append(field)
    return ','.join(res) if res else None

def cmd(*args, **kw):
    if settings.DB_AUTO_MIGRATE:
        logger.info(f'Running auto migrate')
        from . import models
        models.migrate()
    logger.info(f'Starting uvicorn')
    return uvicorn.main.callback('wrep.main:app', *args, **kw)

main = click.Command(
    name='main',
    callback=cmd,
    params=uvicorn.main.params[1:],
    context_settings=uvicorn.main.context_settings)

if __name__ == '__main__':
    main()
