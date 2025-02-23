from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Iterator

import click
import uvicorn

from .. import settings, utils
from ..main import appslist

logger = utils.get_logger('main')


class Command:

    def __init__(self) -> None:
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
        envfile = Path(tempfile.mktemp())
        kw['env_file'] = str(envfile)
        if kw['reload']:
            kw['reload_dirs'] = (
                *kw['reload_dirs'],
                str(settings.BASEDIR))
            kw['reload_includes'] = (
                *kw['reload_includes'],
                *self.reload_extra(role))
        app = f'{self.pkgname}.main:apps.{role}'
        envfile.write_text(f'PROXY_HEADERS={kw['proxy_headers']}')
        try:
            self.delegate.callback(app, **kw)
        finally:
            envfile.unlink(missing_ok=True)

    @classmethod
    def main(cls) -> None:
        cls().run()

    @staticmethod
    def roleopt(ctx, param, value: str) -> str:
        if value not in appslist:
            raise ValueError(value)
        return value

    @staticmethod
    def reload_extra(role: str) -> Iterator[str]:
        yield f'**/*.py'
        yield f'logging.yml'
        if role in ('frontend', 'app'):
            for ext in 'js css scss jinja'.split():
                yield f'frontend/src/**/*.{ext}'

