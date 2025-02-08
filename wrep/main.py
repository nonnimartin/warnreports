from __future__ import annotations

from contextlib import asynccontextmanager

import click
from fastapi import FastAPI, HTTPException, Request, status
from sentry_sdk import capture_exception

from . import frontend, routers, settings, utils
from .backends.mongo import MissingControlDoc
from .models import *

logger = utils.get_logger('main')

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.DB_AUTO_MIGRATE:
        logger.info(f'Running auto migrate')
        from .migrations import migrate
        migrate()
    async with frontend.lifespan(app):
        yield

async def missing_control_doc(req: Request, exc: MissingControlDoc):
    logger.exception(f'Missing control', exc_info=exc)
    capture_exception(exc)
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

def _create_app(**kw):
    kw = dict(
        title='warnreports API',
        openapi_url='/api/v0/openapi.json',
        docs_url='/api/docs/swagger',
        redoc_url='/api/docs/redoc') | kw
    app = FastAPI(**kw)
    app.add_exception_handler(MissingControlDoc, missing_control_doc)
    return app

app = _create_app(lifespan=lifespan)
app.include_router(frontend.router, include_in_schema=False)
app.include_router(routers.backend)
backend_app = _create_app()
backend_app.include_router(routers.backend)
search_app = _create_app()
search_app.include_router(routers.search)
artifacts_app = _create_app(title='warnreports artifacts')
artifacts_app.include_router(routers.artifacts)
frontend_app = _create_app(lifespan=frontend.lifespan, title='warnreports frontend')
frontend_app.include_router(frontend.router, include_in_schema=False)


if __name__ == '__main__':
    import uvicorn

    def cmd(**kw):
        role = kw.pop('role', None)
        if not role or role == 'app':
            appname = 'app'
        elif role in ('backend', 'search', 'artifacts', 'frontend'):
            appname = f'{role}_app'
        else:
            raise ValueError(role) 
        logger.info(f'Starting uvicorn {role=}')
        pkgdirname = settings.BASEDIR.name
        if settings.UVICORN_RELOAD:
            kw.update(
                reload_includes=[
                    f'{pkgdirname}/**/*.py',
                    *map(
                        'frontend/src/**/*.{}'.format,
                        'js css scss jinja2'.split())])
        return uvicorn.main.callback(f'{pkgdirname}.main:{appname}', **kw)
    params = []
    params += [click.Argument(['role'], required=False)]
    params += uvicorn.main.params[1:]
    main = click.Command(
        name='main',
        callback=cmd,
        params=params,
        context_settings=uvicorn.main.context_settings)
    main()
