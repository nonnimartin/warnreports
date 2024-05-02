import click
import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import settings
from .routers import *

app = FastAPI(title='WARN Reporter')

app.include_router(
    prefix='/api/v1',
    router=api.router)

app.include_router(
    prefix='/follow',
    router=follow.router,
    include_in_schema=False)

static = StaticFiles(directory=settings.STATIC_DIR)
app.mount('/static', static, name='static')

@app.get('/', include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse('/follow/new')

main = click.Command(
    name='main',
    callback=lambda *args, **kw: (
        uvicorn.main.callback('wrep.main:app', *args, **kw)),
    params=uvicorn.main.params[1:],
    context_settings=uvicorn.main.context_settings)

if __name__ == '__main__':
    main()
