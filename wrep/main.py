from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from types import SimpleNamespace

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
    if (fwd := req.headers.get('x-forwarded-for')):
        addr = fwd.split(' ')[-1]
        try:
            ip, port = addr.rsplit(':', 1)
            ip = ipaddress.ip_address(ip.strip('[]'))
            req.scope['client'] = (str(ip), int(port))
        except:
            logger.warning(f'Cannot parse x-forwarded-for {addr=}')
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

apps = SimpleNamespace()
apps.frontend = _create_app(lifespan=frontend.lifespan, title='warnreports frontend')
apps.frontend.include_router(frontend.router, include_in_schema=False)
apps.search = _create_app()
apps.search.include_router(routers.search)
apps.artifacts = _create_app(title='warnreports artifacts')
apps.artifacts.include_router(routers.artifacts)
apps.backend = _create_app()
apps.backend.include_router(routers.backend)
apps.app = _create_app(lifespan=frontend.lifespan)
apps.app.include_router(frontend.router, include_in_schema=False)
apps.app.include_router(routers.backend)


if __name__ == '__main__':
    import uvicorn

    def cmd(*, role: str, **kw):
        if not hasattr(apps, role):
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
        return uvicorn.main.callback(f'{pkgdirname}.main:apps.{role}', **kw)
    params = [
        click.Argument(['role'], default='app'),
        *uvicorn.main.params[1:]]
    main = click.Command(
        name='main',
        callback=cmd,
        params=params,
        context_settings=uvicorn.main.context_settings)
    main()
