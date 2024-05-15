from __future__ import annotations

import re
from datetime import datetime
from typing import (Annotated, Any, ClassVar, Generic, Iterable, Iterator,
                    Literal, Self, TypeAlias, TypeVar)
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import peewee as orm
from annotated_types import Le
from peewee import IntegrityError as IntegrityError
from playhouse import db_url
from pydantic import BaseModel as DataModel
from pydantic import (ConfigDict, Field, NonNegativeInt, PositiveInt,
                      StringConstraints, field_serializer)
from pydantic_core import ValidationError as ValidationError

from . import settings, utils
from .ref.tz import zoneinfos

__all__ = ['IntegrityError', 'Naics', 'NaicsReport', 'Report', 'orm']

db: orm.Database = db_url.connect(settings.DB_URL)

class Report(orm.Model):
    NAMESPACE = uuid5(settings.NAMESPACE, 'Report')
    id = orm.UUIDField(primary_key=True)
    company = orm.CharField(max_length=512, index=True)
    state = orm.CharField(max_length=2, index=True)
    created = orm.DateTimeField(index=True, default=utils.now)
    location = orm.CharField(max_length=255, null=True, index=True)
    reported = orm.DateTimeField(index=True)
    starting = orm.DateTimeField(null=True, index=True)
    employees = orm.IntegerField(null=True)
    action = orm.CharField(max_length=64, null=True, index=True)
    url = orm.CharField(max_length=2083, null=True)

    class Meta:
        database = db

    @classmethod
    def select_for_reduce(cls) -> orm.ModelSelect[Self]:
        q = cls.select(NaicsReport, Naics, cls)
        q = q.join_from(cls, NaicsReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(NaicsReport, Naics, orm.JOIN['LEFT_OUTER'])
        q = q.order_by(cls.id, Naics.code)
        return q

class StateStat(orm.Model):
    id = orm.CharField(max_length=2, primary_key=True)
    last_reported = orm.DateTimeField(null=True, index=True)
    reports_count = orm.IntegerField(index=True, default=0)

    class Meta:
        database = db

class Naics(orm.Model):
    id = orm.IntegerField(primary_key=True)
    code = orm.CharField(max_length=32, index=True)
    title = orm.CharField(max_length=255, index=True)

    class Meta:
        database = db

class NaicsReport(orm.Model):
    naics = orm.ForeignKeyField(Naics, on_delete='CASCADE')
    report = orm.ForeignKeyField(Report, on_delete='CASCADE')

    class Meta:
        database = db
        indexes = [(('naics', 'report'), True)]

# ----------------------------

__all__ += [
    'CompanyName',
    'DataModel',
    'Limit',
    'NaicsData',
    'NaicsDetail',
    'Offset',
    'PageNumber',
    'ReportData',
    'StateCode',
    'StateDetail',
    'ValidationError']

DM = TypeVar('DM', bound=DataModel)
Limit = Annotated[NonNegativeInt, Le(1000)]
Offset: TypeAlias = NonNegativeInt
PageNumber: TypeAlias = PositiveInt
CompanyName = Annotated[str, StringConstraints(min_length=1)]
StateCode = Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)]

def tzreplace(dt: datetime|None, tzinfo: ZoneInfo) -> datetime|None:
    return dt and dt.replace(hour=0, tzinfo=tzinfo)

class ReportData(DataModel):
    id: UUID = Field(alias='_id')
    company: CompanyName
    state: StateCode
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

    @field_serializer('reported', 'starting')
    def tzreplace(self, dt: datetime|None, _info=None) -> datetime|None:
        return tzreplace(dt, zoneinfos[self.state])
   
class NaicsData(DataModel):
    id: int
    code: str
    title: str
    model_config = ConfigDict(from_attributes=True)

class NaicsDetail(NaicsData):
    reports_count: int

class StateDetail(DataModel):
    state: StateCode
    last_reported: datetime|None
    reports_count: int
    model_config = ConfigDict(populate_by_name=True,from_attributes=True)

    @field_serializer('last_reported')
    def tzreplace(self, dt: datetime|None, _info=None) -> datetime|None:
        return tzreplace(dt, zoneinfos[self.state])

# ----------------------------

__all__ += ['FilterModel', 'ReportsFilter', 'NaicsFilter', 'StatesFilter']

class FilterModel(DataModel, Generic[DM]):
    order: str|None = None
    result_model: ClassVar[type[DM]]
    order_fields: ClassVar[set[str]] = set()
    default_ordering: ClassVar[list[tuple[str, Literal[1, -1]]]] = []

    def get_ordering(self):
        if self.order:
            yield from self.parse_ordering(self.order, self.order_fields)
        else:
            yield from self.default_ordering

    def parse_ordering(self, order: str, allowed: set[str]|None = None):
        for field in filter(None, re.split(r',\s*', order)):
            if field.startswith('-'):
                field = field[1:]
                dir_ = -1
            else:
                dir_ = 1
            if allowed is None or field in allowed:
                yield field, dir_

class ReportsFilter(FilterModel[ReportData]):
    id: UUID|None = None
    text: str|None = None
    company: CompanyName|None = None
    state: StateCode|None = None
    location: str|None = None
    action: str|None = None
    naics: int|None = None
    reported_after: datetime|None = None
    reported_before: datetime|None = None
    starting_after: datetime|None = None
    starting_before: datetime|None = None
    employees_gt: int|None = None
    employees_lt: int|None = None
    result_model: ClassVar = ReportData
    order_fields: ClassVar = {'reported', 'company', 'state', 'employees', 'starting', 'action'}
    default_ordering: ClassVar = [('reported', -1), ('company', 1), ('state', 1)]

class StatesFilter(FilterModel[StateDetail]):
    state: StateCode|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    last_reported_after: datetime|None = None
    last_reported_before: datetime|None = None
    result_model: ClassVar = StateDetail
    order_fields: ClassVar = {'state', 'reports_count', 'last_reported'}
    default_ordering: ClassVar = [('state', 1)]

class NaicsFilter(FilterModel[NaicsDetail]):
    id: int|None = None
    code: int|None = None
    prefix: int|None = None
    title: str|None = None
    text: str|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    result_model: ClassVar = NaicsDetail
    order_fields: ClassVar = {'id', 'code', 'title', 'reports_count'}
    default_ordering: ClassVar = [('code', 1), ('id', 1)]

# ----------------------------

def migrate() -> None:
    db.create_tables([Report, StateStat, Naics, NaicsReport])

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
        Naics.insert_many(records).on_conflict('IGNORE').execute()

actions = dict(
    migrate=migrate,
    naics=load_naics,
    load_naics=load_naics)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    def run(self):
        actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
