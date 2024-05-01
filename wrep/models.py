from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, TypeAlias
from urllib.parse import urlencode
from uuid import UUID, uuid4, uuid5

import peewee as orm
from annotated_types import Le
from peewee import IntegrityError as IntegrityError
from playhouse import db_url
from pydantic import BaseModel as DataModel
from pydantic import EmailStr, HttpUrl, NonNegativeInt, StringConstraints
from pydantic_core import ValidationError as ValidationError

from . import settings, utils

__all__ = ['Follow', 'IntegrityError', 'Report']

db: orm.Database = db_url.connect(settings.DB_URL)

class OrmModel(orm.Model):
    class Meta:
        database = db

class Report(OrmModel):
    NAMESPACE = uuid5(settings.NAMESPACE, 'Report')
    id = orm.UUIDField(primary_key=True)
    company = orm.CharField(max_length=512, index=True, collation='NOCASE')
    state = orm.CharField(max_length=2, index=True, collation='NOCASE')
    created = orm.DateTimeField(index=True, default=utils.now)
    location = orm.CharField(max_length=255, null=True, index=True, collation='NOCASE')
    reported = orm.DateTimeField(index=True)
    starting = orm.DateTimeField(null=True, index=True)
    employees = orm.IntegerField(null=True)
    action = orm.CharField(max_length=64, null=True, index=True)
    url = orm.CharField(max_length=2083, null=True)

class Follow(OrmModel):
    id = orm.UUIDField(primary_key=True, default=uuid4)
    email = orm.CharField(index=True, collation='NOCASE')
    company = orm.CharField(max_length=512, index=True, collation='NOCASE')
    state = orm.CharField(max_length=2, index=True, default='*', collation='NOCASE')
    created = orm.DateTimeField(index=True, default=utils.now)
    notified = orm.DateTimeField(null=True, index=True)
    confirmed = orm.DateTimeField(null=True, index=True)
    token = orm.UUIDField(unique=True, default=uuid4)

    class Meta:
        indexes = [
            (('email', 'company', 'state'), True),
        ]

    @property
    def confirm_url(self) -> str:
        return self._auth_url('/follow/confirm')

    @property
    def cancel_url(self) -> str:
        return self._auth_url('/follow/cancel')

    def send_confirm_email(self) -> bool:
        return utils.send_email(
            recipient=self.email,
            subject='WARN Notices - Confirm Your Account',
            body=utils.render('email/confirm.jinja', follow=self))

    def _auth_url(self, path: str) -> str:
        query = urlencode(dict(token=self.token, email=self.email))
        return f'{settings.SITE_URL}{path}?{query}'

# ----------------------------

__all__ += [
    'CompanyData',
    'EmailStr',
    'FollowData',
    'Limit',
    'Offset',
    'ReportData',
    'State',
    'StateData',
    'SuccessData',
    'Token',
    'ValidationError']

Token: TypeAlias = UUID
Offset: TypeAlias = NonNegativeInt
Limit = Annotated[NonNegativeInt, Le(1000)]
NonemptyStr = Annotated[str, StringConstraints(min_length=1)]
State = Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)]

class DataModel(DataModel):

    @classmethod
    def orm_fields(cls, model: type[OrmModel]) -> list[orm.Field]:
        return [model._meta.fields[field] for field in cls.model_fields]

class ReportData(DataModel):
    id: UUID
    company: str
    state: State
    location: str|None
    reported: datetime
    starting: datetime|None
    employees: int|None
    action: str|None
    url: HttpUrl|None

    @staticmethod
    def orm_filters(
        search: str|None = None,
        company: str|None = None,
        state: State|None = None,
        location: str|None = None,
    ):
        return (
            not state or Report.state == state,
            not company or Report.company.ilike(f'%{company}%'),
            not location or Report.location.ilike(f'%{location}%'),
            not search or (
                Report.company.ilike(f'%{search}%') |
                Report.location.ilike(f'%{search}%')))

class CompanyData(DataModel):
    company: str
    state: State

class FollowData(DataModel):
    email: EmailStr
    company: NonemptyStr
    state: State|Literal['*'] = '*'

class StateData(DataModel):
    state: State

class SuccessData(DataModel):
    success: Literal[True] = True

# ----------------------------

def migrate() -> None:
    db.create_tables([Report, Follow])

actions = dict(migrate=migrate)

class Command(utils.BaseCommand):

    @classmethod
    def parser(cls):
        parser = super().parser()
        parser.add_argument('action', choices=actions)
        return parser

    def run(self):
        actions[self.opts.action]()

if __name__ == '__main__':
    utils.init_logging()
    Command.main()
