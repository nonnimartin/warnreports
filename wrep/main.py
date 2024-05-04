from __future__ import annotations

import click
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, utils
from .routers import *

app = FastAPI(title='WARN Reporter')
templates = Jinja2Templates(env=utils.jinja_env())

app.include_router(
    prefix='/api/v0',
    router=api.router)

app.include_router(
    prefix='/follow',
    router=follow.router,
    include_in_schema=False)

static = StaticFiles(directory=settings.STATIC_DIR)
app.mount('/static', static, name='static')

@app.get('/', include_in_schema=False)
async def index(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'index.jinja')

main = click.Command(
    name='main',
    callback=lambda *args, **kw: (
        uvicorn.main.callback('wrep.main:app', *args, **kw)),
    params=uvicorn.main.params[1:],
    context_settings=uvicorn.main.context_settings)

if __name__ == '__main__':
    main()
