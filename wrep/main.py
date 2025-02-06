from __future__ import annotations

from contextlib import asynccontextmanager

import click
from fastapi import FastAPI

from . import settings, utils
from .models import *
from .routers import api, feed, frontend

logger = utils.get_logger('main')

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DB_AUTO_MIGRATE:
        logger.info(f'Running auto migrate')
        from .migrations import migrate
        migrate()
    async with frontend.lifespan(app):
        yield

app = FastAPI(
    lifespan=lifespan,
    title='warnreports API',
    docs_url='/api/docs/swagger',
    redoc_url='/api/docs/redoc')
app.include_router(frontend.router, include_in_schema=False)
app.include_router(api.router, prefix='/api/v0')
app.include_router(feed.router, prefix='/feed', include_in_schema=False)


if __name__ == '__main__':
    import uvicorn
    def cmd(*args, **kw):
        logger.info(f'Starting uvicorn')
        kw.update(reload_includes=[
            'wrep/**/*.py',
            *map('frontend/src/**/*.{}'.format, 'js css scss jinja2'.split()),
        ])
        # kw.update(reload_excludes=['.*', '.py[cod]', '~*', f'build/**'])
        return uvicorn.main.callback('wrep.main:app', *args, **kw)
    main = click.Command(
        name='main',
        callback=cmd,
        params=uvicorn.main.params[1:],
        context_settings=uvicorn.main.context_settings)
    main()
