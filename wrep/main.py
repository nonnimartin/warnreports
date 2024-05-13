from __future__ import annotations

from uuid import UUID

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, utils
from .models import *
from .routers import *
from .search import *

app = FastAPI(title='WARN Reporter')
static = StaticFiles(directory=settings.STATIC_DIR)
templates = Jinja2Templates(env=utils.jinja_env())

app.include_router(prefix='/api/v0', router=api.router)
app.include_router(prefix='/feed', router=feed.router)
app.include_router(prefix='/follow', router=follow.router, include_in_schema=False)
app.mount('/static', static, name='static')

@app.get('/', include_in_schema=False)
async def index(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'index.jinja')

@app.get('/r/{id}', include_in_schema=False)
async def report_view(req: Request, id: UUID) -> HTMLResponse:
    try:
        report = await retrieve(ReportData, id=id)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    context = dict(report=report)
    return templates.TemplateResponse(req, 'report.jinja', context)

main = click.Command(
    name='main',
    callback=lambda *args, **kw: (
        uvicorn.main.callback('wrep.main:app', *args, **kw)),
    params=uvicorn.main.params[1:],
    context_settings=uvicorn.main.context_settings)

if __name__ == '__main__':
    main()
