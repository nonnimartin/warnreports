from __future__ import annotations

import asyncio
import enum
import logging
import mimetypes
from argparse import ArgumentParser
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import (Any, AsyncIterable, AsyncIterator, Callable, ClassVar,
                    Iterable, Iterator, TypeVar)
from uuid import UUID

import dateutil.parser

from . import settings

T = TypeVar('T')

def get_logger(name: str|None = None) -> logging.Logger:
    if name:
        name = f'{__package__}.{name}'
    else:
        name = __package__
    return logging.getLogger(name)

logger = get_logger('utils')

def now(**kw) -> datetime:
    dt = datetime.now(tz=kw.pop('tz', None))
    if kw:
        dt += timedelta(**kw)
    return dt

def morethan(n: float, it: Iterable, pred: Callable|None =None) -> bool:
    for i, _ in enumerate(filter(pred, it), start=1):
        if i > n:
            return True
    return False

def unique(it: Iterable[T]) -> Iterator[T]:
    done = set()
    for value in it:
        if value not in done:
            yield value
            done.add(value)

async def as_aiter(it: Iterable[T]|AsyncIterable[T]) -> AsyncIterator[T]:
    if isinstance(it, AsyncIterable):
        async for x in it:
            yield x
    else:
        for x in it:
            yield x

def parse_date(value: str) -> datetime|None:
    value = value or ''
    try:
        dt = dateutil.parser.parse(value, fuzzy=True)
        dt.timestamp()
        return dt
    except ValueError:
        pass

def parse_int(value: str) -> int|None:
    value = value or ''
    try:
        return int(value)
    except ValueError:
        pass

def get_mimetype(value: Any) -> str:
    return mimetypes.guess_type(value)[0] or 'application/octet-stream'

def file_mtime(file: Path) -> datetime:
    return datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)

def render(template: str, *args, **kw) -> str:
    return get_template(template).render(*args, **kw)

def get_template(template: str):
    return jinja_env().get_template(template)

def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return value.hex
    raise TypeError(f'Cannot JSON encode object of type {type(value)}')

def init_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    logging.basicConfig(level=level)

def sync(ret):
    if asyncio.iscoroutine(ret):
        ret = asyncio.run(ret)
    return ret

async def wait(ret):
    if asyncio.iscoroutine(ret):
        ret = await ret
    return ret

from .backends.email import instances as email_backends


def send_email(recipient: str, subject: str, body: str) -> bool:
    backend = email_backends[settings.EMAIL_BACKEND]
    sender = settings.EMAIL_FROM_ADDRESS
    logger.info(f'Sending email {recipient=} {backend=} {subject=}')
    success = backend.send(sender, recipient, subject, body)
    if success:
        logger.info('Email sent successfully!')
    else:
        logger.info('Failed to send email.')
    return success

@cache
def jinja_env():
    import jinja2
    loader = jinja2.FileSystemLoader(settings.TEMPLATES_DIR)
    env = jinja2.Environment(loader=loader)
    env.filters['nf'] = '{:,}'.format
    return env

def build_css():
    logger.info(f'Building css')
    import sass
    context = dict(bootstrap_dir=settings.BOOTSTRAP_DIR)
    outdir = settings.CSS_BUILD_DIR
    outdir.mkdir(parents=True, exist_ok=True)
    content = render('scss/bootstrap.scss', context)
    with Path(outdir, 'bootstrap.css').open('w') as file:
        file.write(sass.compile(string=content))
    with Path(outdir, 'bootstrap.min.css').open('w') as file:
        file.write(sass.compile(string=content, output_style='compressed'))


class CountingIter:

    def __init__(self, it: Iterable[T]):
        self.it = it

    def __iter__(self) -> Iterator[T]:
        self.count = 0
        for x in self.it:
            self.count += 1
            yield x

class StrEnum(str, enum.Enum):

    def __str__(self):
        return self.value

class BaseCommand:
    prog: ClassVar[str|None] = None
    commands: ClassVar[dict[str, type[BaseCommand]]] = {}
    command_metavar: ClassVar[str] = 'command'
    command: BaseCommand|None = None

    @classmethod
    def parser(cls) -> ArgumentParser:
        parser = ArgumentParser()
        cls.init_parser(parser)
        return parser

    @classmethod
    def init_parser(cls, parser: ArgumentParser) -> None:
        parser.description = cls.__doc__
        parser.prog = cls.prog or parser.prog
        cls.add_arguments(parser)
        cls.add_commands(parser)

    @classmethod
    def add_arguments(cls, parser: ArgumentParser) -> None:
        pass

    @classmethod
    def add_commands(cls, parser: ArgumentParser) -> None:
        if not cls.commands:
            return
        subparsers = parser.add_subparsers(
            dest=cls.command_opt,
            metavar=cls.command_metavar,
            help=', '.join(cls.commands),
            required=True)
        for name, cmd in cls.commands.items():
            cmd.init_parser(subparsers.add_parser(name))

    @classmethod
    def main(cls, args=None):
        sync(cls(cls.parse(args)).run())

    @classmethod
    def parse(cls, args=None):
        return cls.parser().parse_args(args)

    @property
    def command_name(self) -> str|None:
        return getattr(self.opts, self.command_opt, None)

    def __init__(self, opts):
        self.opts = opts
        if hasattr(opts, self.command_opt):
            self.command = self.commands[self.command_name](opts)
            delattr(opts, self.command_opt)
        self.setup(opts)

    def setup(self, opts):
        pass

    async def run(self):
        if self.command:
            await wait(self.command.run())

    def __init_subclass__(cls) -> None:
        cls.command_opt = f'_command_{abs(hash(cls))}'

def FuncCommand(f, *bases: type[BaseCommand]) -> type[BaseCommand]:
    class Base:

        async def run(self):
            await wait(self.func(**vars(self.opts)))

    class Command(*bases, Base, BaseCommand):
        __doc__ = f.__doc__
        func = staticmethod(f)

    return Command
