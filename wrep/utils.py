from __future__ import annotations

import asyncio
import dataclasses
import logging
import logging.config
import re
import time
from contextlib import (AbstractAsyncContextManager, AbstractContextManager,
                        asynccontextmanager, contextmanager)
from datetime import datetime, timedelta, timezone
from datetime import tzinfo as TzInfo
from functools import wraps
from typing import (Any, AsyncIterable, AsyncIterator, Callable, ClassVar,
                    Generator, Iterable, Iterator, Mapping, Sequence)
from uuid import UUID

import dateutil.parser
import yaml

type Delta = float|str|timedelta
type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type EitherContext[T] = AbstractContextManager[T]|AbstractAsyncContextManager[T]

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

def now(*, tz: TzInfo|None = None, **deltakw) -> datetime:
    dt = datetime.now(tz=tz)
    if deltakw:
        dt += timedelta(**deltakw)
    return dt

def utcnow(**kw) -> datetime:
    return now(tz=timezone.utc, **kw)

def deltaparse(value: Delta, default_unit: str|None = None) -> timedelta:
    if isinstance(value, timedelta):
        return value
    value = str(value)
    if value.startswith('-'):
        mult = -1
        value = value[1:]
    else:
        mult = 1
    match = DELTA_PAT.match(value)
    if match:
        kw = {
            name: float(value)
            for name, value in match.groupdict().items() if value}
    else:
        if not default_unit:
            raise ValueError(value)
        kw = {default_unit: float(value)}
    return mult * timedelta(**kw)

def deltaopt(default_unit: str):
    timedelta(**{default_unit: 1})
    def opt(value: Delta):
        return deltaparse(value, default_unit=default_unit)
    return opt

def morethan(n: float, it: Iterable, pred: Callable|None = None) -> bool:
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

def parse_date(value: str, *, fail: bool = False) -> datetime|None:
    value = value or ''
    try:
        dt = dateutil.parser.parse(value, fuzzy=True)
        dt.timestamp()
        return dt
    except ValueError:
        if fail:
            raise

def parse_int(value: str, *, fail: bool = False) -> int|None:
    value = value or ''
    try:
        return int(float(value))
    except ValueError:
        if fail:
            raise

def monthend(dt: datetime) -> datetime:
    for days in reversed(range(28, 31)):
        cand = dt + timedelta(days=days)
        if cand.month == dt.month:
            return cand

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
    config['root']['level'] = max(
        ['INFO', levelname],
        key=lambda x: getattr(logging, x))
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
    'Converts a regular function into a context manager function'
    @contextmanager
    @wraps(wrapped)
    def wrapper(*args, **kw) -> Generator[T]:
        yield wrapped(*args, **kw)
    return wrapper

@dataclasses.dataclass(frozen=True, kw_only=True)
class Wait[T]:
    'Async retry/wait parameters'
    timeout: float = 0.0
    'The total time limit'
    poll: float = 0.5
    'Time to wait in between poll'
    ignored: type[Exception]|tuple[type[Exception], ...] = ()
    'Exception types to ignore'
    args: Sequence[Any] = ()
    'Args to pass to the callback'
    kwargs: Mapping = dataclasses.field(default_factory=dict)
    'Kwargs to pass to the callback'
    raises: type[Exception] = dataclasses.field(default_factory=lambda: TimeoutError)
    'The exception class to raise on timeout, default TimeoutError'
    oper: Callable[[Any], Any] = dataclasses.field(default_factory=lambda: bool)
    'The operator to apply to the result of the callback to test for truthiness, default bool'
    callback: Callable[..., T] = dataclasses.field(default_factory=lambda: type(None))
    'The callback function'
    logger: ClassVar = get_logger('utils.wait')

    async def until[T](self, callback: Callable[..., T], /, **kw) -> T:
        return await self(callback=callback, **kw)

    async def __call__(self, **kw) -> T:
        'Wait until the callback returns a truthy value'
        inst = self.replace(**kw) if kw else self
        end = time.monotonic() + inst.timeout
        err = None
        if isinstance(inst.ignored, type):
            ignored = (inst.ignored,)
        else:
            ignored = tuple(inst.ignored or ())
        while True:
            try:
                value = await wait(inst.callback(*inst.args, **inst.kwargs))
                if inst.oper(value):
                    return value
            except ignored as exc:
                err = exc
            if time.monotonic() > end:
                break
            self.logger.debug(f'Retrying in {inst.poll}s {inst.callback.__name__}')
            await asyncio.sleep(inst.poll)
        raise inst.raises from err

    replace = dataclasses.replace
