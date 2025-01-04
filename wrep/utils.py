from __future__ import annotations

import asyncio
import enum
import logging
import mimetypes
from argparse import ArgumentParser, _SubParsersAction
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path
from typing import (Any, AsyncIterable, AsyncIterator, Callable, ClassVar,
                    Iterable, Iterator, TypeVar)
from uuid import UUID

import dateutil.parser

from . import settings

T = TypeVar('T')
type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type SubParsers = _SubParsersAction[ArgumentParser]

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

def as_aiter(it: EitherIterable[T]) -> AsyncIterable[T]:
    return it if isinstance(it, AsyncIterable) else _to_aiter(it)

async def _to_aiter(it: Iterable[T]) -> AsyncIterator[T]:
    for x in it:
        yield x

async def aenumerate(it: EitherIterable[T]) -> AsyncIterator[tuple[int, T]]:
    i = 0
    async for x in as_aiter(it):
        yield i, x
        i += 1

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

async def wait(ret):
    return await ret if asyncio.iscoroutine(ret) else ret

async def amap(func, it):
    async for x in as_aiter(it):
        yield await wait(func(x))

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

class StrEnum(str, enum.Enum):

    def __str__(self):
        return self.value

class BaseCommand:
    description: ClassVar[str|None] = None
    prog: ClassVar[str|None] = None
    commands: ClassVar[dict[str, type[BaseCommand]]] = {}
    command_metavar: ClassVar[str] = 'command'
    command_name: str|None = None
    command: BaseCommand|None = None

    @classmethod
    def parser(cls) -> ArgumentParser:
        parser = ArgumentParser()
        cls.init_parser(parser)
        return parser

    @classmethod
    def init_parser(cls, parser: ArgumentParser) -> None:
        parser.description = (
            cls.__dict__.get('description') or
            cls.__doc__ or
            cls.description)
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
        subparsers = cls.create_subparsers(parser)
        for name, cmd in cls.commands.items():
            subparser = subparsers.add_parser(name)
            cmd.init_parser(subparser)
            if not subparser.description:
                subparser.description = f'{name} command'

    @classmethod
    def create_subparsers(cls, parser: ArgumentParser) -> SubParsers:
        return parser.add_subparsers(
            dest=cls.command_opt,
            metavar=cls.command_metavar,
            help=', '.join(cls.commands),
            required=True)

    @classmethod
    def main(cls, args=None):
        asyncio.run(wait(cls(cls.parse(args)).run()))

    @classmethod
    def parse(cls, args=None):
        return cls.parser().parse_args(args)

    def __init__(self, opts):
        self.opts = opts
        if hasattr(opts, self.command_opt):
            self.command_name = getattr(opts, self.command_opt)
            delattr(opts, self.command_opt)
            self.command = self.commands[self.command_name](opts)
        self.setup(opts)

    def setup(self, opts):
        pass

    async def run(self):
        if self.command:
            await wait(self.command.run())

    def __init_subclass__(cls) -> None:
        cls.command_opt = f'_command_{abs(hash(cls))}'

def FuncCommand(f, *bases: type[BaseCommand]) -> type[BaseCommand]:
    class Base(BaseCommand):

        async def run(self):
            await wait(self.func(**vars(self.opts)))

    class Command(*bases, Base):
        description = f.__doc__
        func = staticmethod(f)

    return Command
