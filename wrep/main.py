from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from functools import cached_property as lazy
from typing import Any, Callable, Coroutine, Sequence

from fastapi import FastAPI, HTTPException, Request, Response, status
from sentry_sdk import capture_exception

from . import frontend, routers, settings, utils
from .backends.mongo import MissingControlDoc

type FNext = Callable[[Request], Coroutine[Any, Any, Response]]
logger = utils.get_logger('main')

appslist: Sequence[str] = []

def wapp[F: Callable](wrapped: F):
    appslist.append(wrapped.__name__)
    return wrapped

class Apps:

    @lazy
    @wapp
    def frontend(self):
        app = self.create_app(
            lifespan=frontend.lifespan,
            title='warnreports frontend')
        app.include_router(frontend.router, include_in_schema=False)
        return app

    @lazy
    @wapp
    def search(self):
        app = self.create_app()
        app.include_router(routers.search)
        return app
    
    @lazy
    @wapp
    def artifacts(self):
        app = self.create_app(title='warnreports artifacts')
        app.include_router(routers.artifacts.router, prefix='/api/v0')
        return app
    
    @lazy
    @wapp
    def backend(self):
        app = self.create_app()
        app.include_router(routers.backend)
        return app
    
    @lazy
    @wapp
    def app(self):
        app = self.create_app(lifespan=frontend.lifespan)
        app.include_router(frontend.router, include_in_schema=False)
        app.include_router(routers.backend)
        return app

    @lazy
    @wapp
    def noop(self):
        return FastAPI(lifespan=self.default_lifespan)

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
        if settings.PROXY_HEADERS and (fwd := req.headers.get('x-forwarded-for')):
            try:
                addr = fwd.rsplit(None, 1)[-1]
                ip, port = addr.rsplit(':', 1)
                ip = ipaddress.ip_address(ip.strip('[]'))
                req.scope['client'] = (str(ip), int(port))
            except:
                logger.warning(f'Cannot parse x-forwarded-for {fwd=}')
        return await call_next(req)

appslist = tuple(appslist)
apps = Apps()

if __name__ == '__main__':
    from .cli.main import Command
    Command.main()
