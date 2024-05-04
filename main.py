from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import settings
from routers import *

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
