from __future__ import annotations

from contextlib import asynccontextmanager

import click
from fastapi import FastAPI, HTTPException, Request, status
from sentry_sdk import capture_exception

from . import frontend, routers, settings, utils
from .backends.mongo import MissingControlDoc
from .models import *

logger = utils.get_logger('main')


async def missing_control_doc(req: Request, exc: MissingControlDoc):
    logger.exception(f'Missing control', exc_info=exc)
    capture_exception(exc)
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

@asynccontextmanager
async def _default_lifespan(app: FastAPI):
    utils.init_logging()
    yield

async def set_proxy_client(req: Request, call_next):
    fwd = req.headers.get('x-forwarded-for')
    if fwd:
        port = req.client.port
        prt = req.headers.get('x-forwarded-port')
        if prt:
            try:
                port = int(prt.split(' ')[-1])
            except ValueError:
                logger.warning(f'Invalid port in {prt}', exc_info=True)
        req.scope['client'] = (fwd.split(' ')[-1], port)
    return await call_next(req)

def _create_app(**kw):
    kw = dict(
        lifespan=_default_lifespan,
        title='warnreports API',
        openapi_url='/api/v0/openapi.json',
        docs_url='/api/docs/swagger',
        redoc_url='/api/docs/redoc') | kw    
    app = FastAPI(**kw)
    if settings.UVICORN_PROXY_HEADERS:
        app.middleware('http')(set_proxy_client)
    app.add_exception_handler(MissingControlDoc, missing_control_doc)
    return app

app = _create_app(lifespan=frontend.lifespan)
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

    def cmd(*, role: str, **kw):
        if role == 'app':
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
                    f'{pkgdirname}/logging.yml',
                    *map(
                        f'{pkgdirname}/''frontend/src/**/*.{}'.format,
                        'js css scss jinja'.split())])
        return uvicorn.main.callback(f'{pkgdirname}.main:{appname}', **kw)
    params = [
        click.Argument(['role'], default='app'),
        *uvicorn.main.params[1:]]
    main = click.Command(
        name='main',
        callback=cmd,
        params=params,
        context_settings=uvicorn.main.context_settings)
    main()
