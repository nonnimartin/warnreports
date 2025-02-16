from __future__ import annotations

import argparse
import asyncio
import builtins
import enum
import logging
import logging.config
import mimetypes
import re
from argparse import ArgumentParser, _SubParsersAction
from contextlib import (AbstractAsyncContextManager, AbstractContextManager,
                        asynccontextmanager)
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import (TYPE_CHECKING, Any, AsyncIterable, AsyncIterator, Callable,
                    ClassVar, Iterable, Iterator)
from uuid import UUID

import dateutil.parser
import yaml

type AP = ArgumentParser
type Delta = float|str|timedelta
type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type EitherContext[T] = AbstractContextManager[T]|AbstractAsyncContextManager[T]
type SubParsers = _SubParsersAction[ArgumentParser]
type SrchRepl = tuple[str|re.Pattern, str|Callable[[re.Match], str]]

def get_logger(name: str|None = None) -> logging.Logger:
    if name:
        name = f'{__package__}.{name}'
    else:
        name = __package__
    return logging.getLogger(name)

logger = get_logger('utils')

DELTA_PAT = re.compile(
    r'^((?P<weeks>[\d.]+?)w)?'
    r'((?P<days>[\d.]+?)d)?'
    r'((?P<hours>[\d.]+?)h)?'
    r'((?P<minutes>[\d.]+?)m)?'
    r'((?P<seconds>[\d.]+?)s)?'
    r'((?P<milliseconds>[\d.]+?)ms)?'
    r'((?P<microseconds>[\d.]+?)us)?$')

def now(**kw) -> datetime:
    dt = datetime.now(tz=kw.pop('tz', None))
    if kw:
        dt += timedelta(**kw)
    return dt

def utcnow(**kw) -> datetime:
    return now(tz=timezone.utc, **kw)

def deltaparse(value: Delta, default_unit: str|None = None) -> timedelta:
    if isinstance(value, timedelta):
        return value
    value = str(value)
    match = DELTA_PAT.match(value)
    if match:
        kw = {
            name: float(value)
            for name, value in match.groupdict().items() if value}
    else:
        if not default_unit:
            raise ValueError(value)
        kw = {default_unit: float(value)}
    return timedelta(**kw)

def deltaopt(default_unit: str):
    timedelta(**{default_unit: 1})
    def opt(value: Delta):
        return deltaparse(value, default_unit=default_unit)
    return opt

def morethan(n: float, it: Iterable, pred: Callable|None =None) -> bool:
    for i, _ in enumerate(filter(pred, it), start=1):
        if i > n:
            return True
    return False

def unique[T](it: Iterable[T]) -> Iterator[T]:
    done = set()
    for value in it:
        if value not in done:
            yield value
            done.add(value)

def as_aiter[T](it: EitherIterable[T]) -> AsyncIterable[T]:
    return it if isinstance(it, AsyncIterable) else _to_aiter(it)

async def _to_aiter[T](it: Iterable[T]) -> AsyncIterator[T]:
    for x in it:
        yield x

async def aenumerate[T](it: EitherIterable[T]) -> AsyncIterator[tuple[int, T]]:
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

def rewrite_all(value: str, rewrites: Iterable[SrchRepl]) -> str:
    for srch, repl in rewrites:
        if srch == value:
            value = repl
        elif isinstance(srch, re.Pattern):
            value = srch.sub(repl, value)
    return value

def get_mimetype(value: Any) -> str:
    return mimetypes.guess_type(value)[0] or 'application/octet-stream'

def file_mtime(file: Path) -> datetime:
    return datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc)

def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return value.hex
    raise TypeError(f'Cannot JSON encode object of type {type(value)}')

def init_logging() -> None:
    from . import settings
    levelname = settings.LOG_LEVEL.upper()
    file = settings.BASEDIR/'logging.yml'
    config = yaml.safe_load(file.read_bytes())
    config['loggers']['wrep']['level'] = levelname
    config['root']['level'] = sorted(
        ['INFO', levelname],
        key=lambda x: getattr(logging, x)).pop()
    logging.config.dictConfig(config)

async def wait(ret):
    return await ret if asyncio.iscoroutine(ret) else ret

async def amap[T, R](func: Callable[[T], R], it: EitherIterable[T]) -> AsyncIterator[R]:
    async for x in as_aiter(it):
        yield await wait(func(x))

@asynccontextmanager
async def awith[T](ctx: EitherContext[T]):
    if isinstance(ctx, AbstractAsyncContextManager):
        async with ctx as it:
            yield it
    else:
        with ctx as it:
            yield it

async def achain_from_iterable[T](it: EitherIterable[EitherIterable[T]]) -> AsyncIterator[T]:
    async for it in as_aiter(it):
        async for x in as_aiter(it):
            yield x

def lazyprop[S, T](wrapped: Callable[..., T]) -> property[S, T]:
    name = wrapped.__name__
    @wraps(wrapped)
    def wrapper(self: S) -> T:
        try:
            return self.__dict__[name]
        except KeyError:
            return self.__dict__.setdefault(name, wrapped(self))
    return property(wrapper)

from .backends.email import instances as email_backends


def send_email(recipient: str, subject: str, body: str) -> bool:
    from . import settings
    backend = email_backends[settings.EMAIL_BACKEND]
    sender = settings.EMAIL_FROM_ADDRESS
    logger.info(f'Sending email {recipient=} {backend=} {subject=}')
    success = backend.send(sender, recipient, subject, body)
    if success:
        logger.info('Email sent successfully!')
    else:
        logger.info('Failed to send email.')
    return success


class StrEnum(str, enum.Enum):

    def __str__(self):
        return self.value


class HelpFormatter(argparse.HelpFormatter):
    """
    From: https://gist.github.com/panzi/b4a51b3968f67b9ff4c99459fb9c5b3d
    Author: Mathias Panzenböck
    """

    def _split_lines(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for line_str in text.split('\n'):
            line: list[str] = []
            line_len = 0
            for word in line_str.split():
                word_len = len(word)
                line_len += word_len + bool(line)
                if line_len > width:
                    lines.append(' '.join(line))
                    line.clear()
                    line_len = word_len
                line.append(word)
            lines.append(' '.join(line))
        return lines
    
    def _fill_text(self, text: str, width: int, indent: str) -> str:
        return '\n'.join(indent + line for line in self._split_lines(text, width - len(indent)))

class BaseCommand:
    description: ClassVar[str|None] = None
    prog: ClassVar[str|None] = None
    usage: ClassVar[str|None] = None
    parser_class: ClassVar[type[AP]] = ArgumentParser
    formatter_class: ClassVar[type[argparse.HelpFormatter]] = HelpFormatter
    commands: ClassVar[dict[str, type[BaseCommand]]] = {}
    command_metavar: ClassVar[str] = 'command'
    command_name: str|None = None
    command: BaseCommand|None = None

    @classmethod
    def create_parser(cls) -> AP:
        parser = cls.parser_class()
        cls.init_parser(parser)
        return parser

    @classmethod
    def init_parser(cls, parser: AP) -> None:
        parser.formatter_class = cls.formatter_class
        parser.description = cls.description
        parser.prog = cls.prog or parser.prog
        parser.usage = cls.usage or parser.usage
        cls.add_arguments(parser)
        cls.add_commands(parser)
        fmt = cls.parser_fmtargs(parser)
        if parser.description:
            parser.description = parser.description.format(**fmt)
        if parser.usage:
            parser.usage = parser.usage.format(**fmt)

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        pass

    @classmethod
    def add_commands(cls, parser: AP) -> None:
        if not cls.commands:
            return
        subparsers = cls.create_subparsers(parser)
        for name, cmd in cls.commands.items():
            subparser = subparsers.add_parser(name)
            cmd.init_parser(subparser)
            if not subparser.description:
                subparser.description = f'{name} command'

    @classmethod
    def create_subparsers(cls, parser: AP) -> SubParsers:
        return parser.add_subparsers(
            dest=cls.command_opt,
            metavar=cls.command_metavar,
            help=', '.join(cls.commands),
            required=True)

    @classmethod
    def parser_fmtargs(cls, parser: AP) -> dict[str, Any]:
        return dict(prog=parser.prog)

    @classmethod
    def main(cls, args=None):
        parser = cls.create_parser()
        opts = parser.parse_args(args)
        cmd = cls(opts, parser)
        asyncio.run(wait(cmd.run()))

    def __init__(self, opts, parser: AP):
        self.opts = opts
        self.parser = parser
        if hasattr(opts, self.command_opt):
            self.command_name = getattr(opts, self.command_opt)
            delattr(opts, self.command_opt)
            self.command = self.commands[self.command_name](opts, parser)
        self.setup(opts)

    def setup(self, opts):
        pass

    async def run(self):
        if self.command:
            await wait(self.command.run())

    def __init_subclass__(cls) -> None:
        cls.command_opt = f'_command_{abs(hash(cls))}'
        cls.description = (
            cls.__dict__.get('description') or
            cls.__doc__ or
            cls.description)

def FuncCommand(f, *bases: type[BaseCommand]) -> type[BaseCommand]:
    class Base(BaseCommand):
        func = staticmethod(f)

        async def run(self):
            await wait(self.func(**vars(self.opts)))

    class Command(*bases, Base):
        description = f.__doc__

    return Command

if TYPE_CHECKING:
    from typing import overload
    class property[S, T](builtins.property):
        fget: Callable[[S], Any] | None
        fset: Callable[[S, Any], None] | None
        fdel: Callable[[S], None] | None
        @overload
        def __init__(
            self,
            fget: Callable[[S], T] | None = ...,
            fset: Callable[[S, Any], None] | None = ...,
            fdel: Callable[[S], None] | None = ...,
            doc: str | None = ...,
        ) -> None: ...
        def getter(self, __fget: Callable[[S], T]) -> property[S, T]: ...
        def setter(self, __fset: Callable[[S, Any], None]) -> property[S, T]: ...
        def deleter(self, __fdel: Callable[[S], None]) -> property[S, T]: ...
        def __get__(self, __obj: S, __type: type | None = ...) -> T: ...
        def __set__(self, __obj: S, __value: Any) -> None: ...
        def __delete__(self, __obj: S) -> None: ...
