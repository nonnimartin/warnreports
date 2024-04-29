from __future__ import annotations

import enum
import io
import json
import logging
import os.path
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

import boto3
import dateutil.parser
import jinja2

import settings

jinja = jinja2.Environment(loader=jinja2.FileSystemLoader(settings.TEMPLATES_DIR))

def now(**kw) -> datetime:
    dt = datetime.now(tz=kw.pop('tz', None))
    if kw:
        dt += timedelta(**kw)
    return dt

def parse_date(value: str) -> datetime|None:
    if not (value and has_digit(value)):
        return
    try:
        dt = dateutil.parser.parse(value, fuzzy=True)
        dt.timestamp()
        if dt.year > 1:
            return dt
    except ValueError:
        pass

def parse_int(value: str) -> int|None:
    if not (value and has_digit(value)):
        return
    try:
        return int(value)
    except ValueError:
        pass

def has_digit(input: str) -> bool:
    return any(filter(str.isdigit, input))

def render(template: str, *args, **kw) -> str:
    return jinja.get_template(template).render(*args, **kw)

def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return value.hex
    raise TypeError(f'Cannot JSON encode object of type {type(value)}')

def json_lines(fp: io.TextIOBase) -> Iterator[Any]:
    while True:
        line = fp.readline()
        if not line:
            break
        yield json.loads(line)

def init_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL, logging.INFO)
    logging.basicConfig(level=level)

def makedirs(path: Path) -> None:
    if not os.path.exists(path):
        os.makedirs(path)

def send_email(recipient: str, subject: str, body: str) -> bool:
    backend = email_backends[settings.EMAIL_BACKEND]
    sender = settings.EMAIL_ACCOUNT
    logging.info(f'Sending email {recipient=} {backend=} {subject=}')
    success = backend.send(sender, recipient, subject, body)
    if success:
        logging.info('Email sent successfully!')
    else:
        logging.info('Failed to send email.')
    return success

class SesEmailBackend:

    @staticmethod
    def send(sender: str, recipient: str, subject: str, body: str) -> bool:
        response = boto3.client('ses').send_email(
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
        logging.info(f'{sender=} {recipient=} {subject=} {body=}')
        return True

email_backends = {
    'ses': SesEmailBackend(),
    'debug': DebugEmailBackend()}

class StrEnum(str, enum.Enum):

    def __str__(self):
        return self.value
