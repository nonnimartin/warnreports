from __future__ import annotations

from pathlib import Path
from uuid import UUID

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, utils
from .models import *
from .routers import *
from .search import *

logger = utils.get_logger('main')
app = FastAPI(title='WARN Reporter')
static = StaticFiles(directory=settings.STATIC_DIR)
templates = Jinja2Templates(env=utils.jinja_env())

app.include_router(prefix='/api/v0', router=api.router)
app.include_router(prefix='/feed', router=feed.router)
app.mount('/static', static, name='static')

@app.get('/', include_in_schema=False)
async def index(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'index.jinja')

@app.get('/r/{id}', include_in_schema=False)
async def report_view(req: Request, id: UUID) -> HTMLResponse:
    report = await retrieve404(ReportData, id=id)
    context = dict(report=report)
    return templates.TemplateResponse(req, 'report.jinja', context)

@app.get('/d/{id}', include_in_schema=False)
async def artifact_download(id: UUID) -> FileResponse:
    try:
        artifact: Artifact = Artifact.get_by_id(id)
    except Artifact.DoesNotExist:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    path = Path(settings.ARTIFACTS_DIR, artifact.path)
    return FileResponse(path, media_type=artifact.mimetype, filename=artifact.name)

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
