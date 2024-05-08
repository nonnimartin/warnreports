from __future__ import annotations

from datetime import datetime
from typing import (Annotated, Any, Iterable, Iterator, Literal, Self,
                    Sequence, TypeAlias)
from urllib.parse import urlencode
from uuid import UUID, uuid4, uuid5

import peewee as orm
from annotated_types import Le
from peewee import IntegrityError as IntegrityError
from playhouse import db_url
from pydantic import BaseModel as DataModel
from pydantic import (ConfigDict, EmailStr, Field, NonNegativeInt,
                      StringConstraints)
from pydantic_core import ValidationError as ValidationError

from . import settings, utils

__all__ = ['Follow', 'IntegrityError', 'Naics', 'NaicsReport', 'Report', 'orm']

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

    @classmethod
    def select_for_reduce(cls) -> orm.ModelSelect[Self]:
        q = cls.select(NaicsReport, Naics, cls)
        q = q.join_from(cls, NaicsReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(NaicsReport, Naics, orm.JOIN['LEFT_OUTER'])
        q = q.order_by(cls.id, Naics.code)
        return q

class Naics(OrmModel):
    id = orm.IntegerField(primary_key=True)
    code = orm.CharField(max_length=32, index=True)
    title = orm.CharField(max_length=255, index=True, collation='NOCASE')

class NaicsReport(OrmModel):
    naics = orm.ForeignKeyField(Naics, on_delete='CASCADE')
    report = orm.ForeignKeyField(Report, on_delete='CASCADE')

    class Meta:
        indexes = [
            (('naics', 'report'), True)
        ]

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
    'DataModel',
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

class ReportData(DataModel):
    id: UUID = Field(alias='_id')
    company: str
    state: State
    location: str|None
    reported: datetime
    starting: datetime|None
    employees: int|None
    action: str|None
    url: str|None
    naics: list[NaicsData] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True)

    @classmethod
    def map_reduce(cls, it: Iterable[Report]|None = None) -> Iterator[Self]:
        if it is None:
            it = Report.select_for_reduce()
        inst: Self|None = None
        for report in it:
            if inst is None or inst.id != report.id:
                if inst:
                    yield inst
                inst = cls.model_validate(report)
            inst.reduce_obj(report)
        if inst:
            yield inst

    def reduce_obj(self, report: Report) -> None:
        nr = getattr(report, 'naicsreport', None)
        if isinstance(nr, NaicsReport):
            naics = NaicsData.model_validate(nr.naics)
            self.naics.append(naics)

    def as_doc(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)

class NaicsData(DataModel):
    id: int
    code: str
    title: str
    model_config = ConfigDict(from_attributes=True)

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

__all__ += ['ReportsFilter', 'CompaniesFilter', 'StatesFilter']

class ReportsFilter(DataModel):
    text: str|None = None
    company: str|None = None
    state: State|None = None
    location: str|None = None
    naics: int|None = None
    reported_after: datetime|None = None
    reported_before: datetime|None = None
    ordering: Sequence[Any] = ()

class CompaniesFilter(DataModel):
    text: str|None = None
    company: str|None = None
    state: State|None = None
    ordering: Sequence[Any] = ()

class StatesFilter(DataModel):
    state: State|None = None
    ordering: Sequence[Any] = ()

# ----------------------------

async def migrate() -> None:
    db.create_tables([Report, Naics, NaicsReport, Follow])

def load_naics() -> None:
    import requests
    rep = requests.get(settings.NAICS_DOWNLOAD)
    rep.raise_for_status()
    records = (
        dict(
            id=entry['code'],
            code=entry['code_raw'],
            title=entry['title'])
        for entry in rep.json())
    with db.atomic():
        Naics.replace_many(records).execute()

actions = dict(
    migrate=migrate,
    load_naics=load_naics)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    async def run(self):
        await actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
