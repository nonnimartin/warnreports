from __future__ import annotations

import asyncio
import csv
import enum
import hashlib
import io
import json
import logging
from argparse import ArgumentParser
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from uuid import UUID

import dateutil.parser

from . import settings


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

def hashfile(path: Path, alg: str = 'sha1', missing_ok: bool = False) -> str|None:
    try:
        return hashlib.new(alg, path.read_bytes()).hexdigest()
    except FileNotFoundError:
        if not missing_ok:
            raise

def morethan(n: float, it: Iterable, pred: Callable|None =None) -> bool:
    for i, _ in enumerate(filter(pred, it), start=1):
        if i > n:
            return True
    return False

@contextmanager
def csvdicts(path: Path, **kw):
    with open(path) as file:
        yield csv.DictReader(file, **kw)

@contextmanager
def logdicts(path: Path):
    with open(path) as file:
        yield logdict_reader(file)

def logdict_reader(file: io.TextIOWrapper) -> Iterator[dict[str, str]]:
    while True:
        line = file.readline()
        if not line:
            break
        yield json.loads(line)

async def as_aiter(it):
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
    return jinja_env().get_template(template).render(*args, **kw)

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
        ret = asyncio.get_event_loop().run_until_complete(ret)
    return ret

def send_email(recipient: str, subject: str, body: str) -> bool:
    backend = email_backends[settings.EMAIL_BACKEND]
    sender = settings.EMAIL_ACCOUNT
    logger.info(f'Sending email {recipient=} {backend=} {subject=}')
    success = backend.send(sender, recipient, subject, body)
    if success:
        logger.info('Email sent successfully!')
    else:
        logger.info('Failed to send email.')
    return success

class SesEmailBackend:

    @property
    @cache
    def client(self):
        import boto3
        return boto3.client('ses')

    def send(self, sender: str, recipient: str, subject: str, body: str) -> bool:
        response = self.client.send_email(
            Source=sender,
            Destination={'ToAddresses': [recipient]},
            Message={
                'Subject': {'Data': subject},
                'Body': {
                    fmt: {'Data': body,'Charset': 'UTF-8'}
                    for fmt in ('Text', 'Html')}})
        return response['ResponseMetadata']['HTTPStatusCode'] == 200

class DebugEmailBackend:

    @staticmethod
    def send(sender: str, recipient: str, subject: str, body: str) -> bool:
        logger.info(f'{sender=} {recipient=} {subject=} {body=}')
        return True

email_backends = {
    'ses': SesEmailBackend(),
    'debug': DebugEmailBackend()}

@cache
def jinja_env():
    import jinja2
    loader = jinja2.FileSystemLoader(settings.TEMPLATES_DIR)
    return jinja2.Environment(loader=loader)

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

class Stage(StrEnum):
    Extract = 'extract'
    Translate = 'translate'
    Load = 'load'
    Index = 'index'

    @property
    def dir(self) -> Path:
        return settings.BUILD_DIR/self

    @property
    def ext(self) -> str|None:
        if self is self.Extract:
            return 'csv'
        if self is self.Translate:
            return 'log'

    def file(self, state: str) -> Path|None:
        if self.ext:
            return Path(self.dir, f'{state.lower()}.{self.ext}')
