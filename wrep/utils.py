from __future__ import annotations

import asyncio
import dataclasses
import enum
import logging
import logging.config
import mimetypes
import re
import time
from contextlib import (AbstractAsyncContextManager, AbstractContextManager,
                        asynccontextmanager, contextmanager)
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import (Any, AsyncIterable, AsyncIterator, Callable, Generator,
                    Iterable, Iterator, Sequence)
from uuid import UUID

import dateutil.parser
import yaml

type Delta = float|str|timedelta
type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type EitherContext[T] = AbstractContextManager[T]|AbstractAsyncContextManager[T]
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

def monthend(dt: datetime) -> datetime:
    for days in reversed(range(28, 31)):
        cand = dt + timedelta(days=days)
        if cand.month == dt.month:
            return cand

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

def digestfile(file: Path) -> Path:
    return file.parent/f'.{file.name}.sha1'

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

async def astarmap[**P, R](func: Callable[P, R], it: EitherIterable[P]) -> AsyncIterator[R]:
    async for args in as_aiter(it):
        yield await wait(func(*args))

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

def wrapcontext[T](wrapped: Callable[..., T]):
    @contextmanager
    @wraps(wrapped)
    def wrapper(*args, **kw) -> Generator[T]:
        yield wrapped(*args, **kw)
    return wrapper

class StrEnum(str, enum.Enum):

    def __str__(self):
        return self.value

@dataclasses.dataclass(frozen=True)
class Wait:
    timeout: float
    poll: float = 0.5
    ignored: tuple[type[Exception], ...] = ()
    args: Sequence[Any] = ()
    kwargs: dict = dataclasses.field(default_factory=dict)
    raises: type[Exception] = dataclasses.field(default_factory=lambda: TimeoutError)
    oper: Callable[[Any], Any] = dataclasses.field(default_factory=lambda: bool)

    async def until[T](self, callback: Callable[..., T]) -> T:
        end = time.monotonic() + self.timeout
        err = None
        ignored = tuple(self.ignored or ())
        while True:
            try:
                value = callback(*self.args, **self.kwargs)
                if self.oper(value):
                    return value
            except ignored as exc:
                err = exc
            if time.monotonic() > end:
                break
            await asyncio.sleep(self.poll)
        raise self.raises from err

    replace = dataclasses.replace

def send_email(recipient: str, subject: str, body: str) -> bool:
    from . import settings
    from .backends.email import instances as email_backends
    backend = email_backends[settings.EMAIL_BACKEND]
    sender = settings.EMAIL_FROM_ADDRESS
    logger.info(f'Sending email {recipient=} {backend=} {subject=}')
    success = backend.send(sender, recipient, subject, body)
    if success:
        logger.info('Email sent successfully!')
    else:
        logger.info('Failed to send email.')
    return success
