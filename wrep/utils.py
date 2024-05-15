from __future__ import annotations

import asyncio
import enum
import logging
from argparse import ArgumentParser
from datetime import datetime, timedelta
from functools import cache
from typing import (Any, AsyncIterable, AsyncIterator, Callable, Iterable,
                    Iterator, TypeVar)
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
    return jinja2.Environment(loader=loader)

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

    @classmethod
    def parser(cls) -> ArgumentParser:
        parser = ArgumentParser(description=cls.__doc__)
        cls.add_arguments(parser)
        return parser

    @classmethod
    def add_arguments(cls, parser: ArgumentParser) -> None:
        pass

    @classmethod
    def main(cls, args=None):
        sync(cls(cls.parse(args)).run())

    @classmethod
    def parse(cls, args=None):
        return cls.parser().parse_args(args)

    def __init__(self, opts):
        self.opts = opts
        self.setup(opts)

    def setup(self, opts):
        pass

    async def run(self):
        pass
