from __future__ import annotations

import logging
import logging.config
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from datetime import tzinfo as TzInfo
from functools import wraps
from typing import Any, Callable, Generator, Iterable, Iterator
from uuid import UUID

import dateutil.parser
import yaml

type Delta = float|str|timedelta

logger = logging.getLogger(__name__)

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
    with file.open('rb') as fp:
        config = yaml.safe_load(fp)
    for pkg in ('wrep', 'warn'):
        config['loggers'][pkg]['level'] = levelname
    config['root']['level'] = max(
        ['INFO', levelname],
        key=logging.getLevelNamesMapping().__getitem__)
    logging.config.dictConfig(config)

def wrapcontext[T](wrapped: Callable[..., T]):
    'Converts a regular function into a context manager function'
    @contextmanager
    @wraps(wrapped)
    def wrapper(*args, **kw) -> Generator[T]:
        yield wrapped(*args, **kw)
    return wrapper
