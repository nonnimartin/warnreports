from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, Callable, Coroutine, Iterator, Sequence

from fastapi import FastAPI, HTTPException, Request, Response, status
from sentry_sdk import capture_exception

from . import frontend, routers, settings, utils
from .backends.mongo import MissingControlDoc
from .models import *

type FNext = Callable[[Request], Coroutine[Any, Any, Response]]
logger = utils.get_logger('main')


class Apps:

    appslist: Sequence[str] = []
    opts: dict[str, Any] = dict(proxy_headers=False)

    def wapp[T, F: Callable[[T], FastAPI]](wrapped: F, appslist: list = appslist) -> property[FastAPI]:
        name = wrapped.__name__
        appslist.append(name)
        @wraps(wrapped)
        def wrapper(self: T) -> FastAPI:
            try:
                return self.__dict__[name]
            except KeyError:
                return self.__dict__.setdefault(name, wrapped(self))
        return property(wrapper)

    @wapp
    def frontend(self):
        app = self.create_app(
            lifespan=frontend.lifespan,
            title='warnreports frontend')
        app.include_router(frontend.router, include_in_schema=False)
        return app

    @wapp
    def search(self):
        app = self.create_app()
        app.include_router(routers.search)
        return app
    
    @wapp
    def artifacts(self):
        app = self.create_app(title='warnreports artifacts')
        app.include_router(routers.artifacts)
        return app
    
    @wapp
    def backend(self):
        app = self.create_app()
        app.include_router(routers.backend)
        return app
    
    @wapp
    def app(self):
        app = self.create_app(lifespan=frontend.lifespan)
        app.include_router(frontend.router, include_in_schema=False)
        app.include_router(routers.backend)
        return app

    del(wapp)
    appslist = tuple(appslist)

    def create_app(self, **kw) -> FastAPI:
        kw = dict(
            lifespan=self.default_lifespan,
            title='warnreports API',
            openapi_url='/api/v0/openapi.json',
            docs_url='/api/docs/swagger',
            redoc_url='/api/docs/redoc') | kw    
        app = FastAPI(**kw)
        app.middleware('http')(self.set_proxy_client)
        app.add_exception_handler(MissingControlDoc, self.missing_control_doc)
        return app

    @asynccontextmanager
    async def default_lifespan(self, app: FastAPI):
        utils.init_logging()
        yield

    async def missing_control_doc(self, req: Request, exc: MissingControlDoc) -> None:
        logger.exception(f'Missing control', exc_info=exc)
        capture_exception(exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)

    async def set_proxy_client(self, req: Request, call_next: FNext) -> Response:
        if self.opts['proxy_headers'] and (fwd := req.headers.get('x-forwarded-for')):
            try:
                addr = fwd.rsplit(None, 1)[-1]
                ip, port = addr.rsplit(':', 1)
                ip = ipaddress.ip_address(ip.strip('[]'))
                req.scope['client'] = (str(ip), int(port))
            except:
                logger.warning(f'Cannot parse x-forwarded-for {fwd=}')
        return await call_next(req)

apps = Apps()

del(Apps)

class Command:

    def __init__(self) -> None:
        import click
        import uvicorn
        self.pkgname = settings.BASEDIR.name
        self.delegate = uvicorn.main
        self.run = click.Command(
            name='main',
            callback=self,
            params=[
                click.Argument(
                    ['role'],
                    default='app',
                    callback=self.roleopt,
                    envvar='UVICORN_ROLE'),
                *self.delegate.params[1:]],
            context_settings=self.delegate.context_settings)

    def __call__(self, /, *, role: str, **kw) -> None:
        logger.info(f'Starting uvicorn {role=}')
        apps.opts['proxy_headers'] = kw['proxy_headers']
        if kw['reload']:
            kw['reload_dirs'] = (
                *kw['reload_dirs'],
                str(settings.BASEDIR))
            kw['reload_includes'] = (
                *kw['reload_includes'],
                *self.reload_extra(role))
        app = f'{self.pkgname}.main:apps.{role}'
        self.delegate.callback(app, **kw)

    @classmethod
    def main(cls):
        cls().run()

    @staticmethod
    def roleopt(ctx, param, value: str) -> str:
        if value not in apps.appslist:
            raise ValueError(value)
        return value

    @staticmethod
    def reload_extra(role: str) -> Iterator[str]:
        yield f'**/*.py'
        yield f'logging.yml'
        if role in ('frontend', 'app'):
            for ext in 'js css scss jinja'.split():
                yield f'frontend/src/**/*.{ext}'

if __name__ == '__main__':
    Command.main()
