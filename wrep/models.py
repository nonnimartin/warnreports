from __future__ import annotations

import hashlib
import re
from abc import abstractmethod
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import (Annotated, Any, ClassVar, Generic, Iterable, Iterator,
                    Literal, Self, TypeAlias, TypeVar)
from uuid import UUID
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

logger = utils.get_logger('models')

__all__ = [
    'Artifact',
    'ArtifactReport',
    'Company',
    'IntegrityError',
    'Naics',
    'NaicsReport',
    'orm',
    'Report',
    'StateStat']

db: orm.Database = db_url.connect(settings.DB_URL)

class OrmModel(orm.Model):
    class Meta:
        database = db

    @classmethod
    def select_for_reduce(cls) -> orm.ModelSelect[Self]:
        return cls.select()

class Report(OrmModel):
    id = orm.UUIDField(primary_key=True)
    company = orm.CharField(max_length=512, index=True)
    state = orm.CharField(max_length=2, index=True)
    created = orm.DateTimeField(index=True, default=utils.now)
    location = orm.CharField(max_length=255, null=True)
    reported = orm.DateTimeField(index=True)
    starting = orm.DateTimeField(null=True)
    employees = orm.IntegerField(null=True)
    action = orm.CharField(max_length=64, null=True)
    url = orm.CharField(max_length=2083, null=True)

    @classmethod
    def select_for_reduce(cls):
        q = cls.select(NaicsReport, Naics, ArtifactReport, Artifact, cls)
        q = q.join_from(cls, NaicsReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(NaicsReport, Naics, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(cls, ArtifactReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(ArtifactReport, Artifact, orm.JOIN['LEFT_OUTER'])
        q = q.order_by(cls.id, Naics.id, Artifact.id)
        return q

class StateStat(OrmModel):
    id = orm.CharField(max_length=2, primary_key=True)
    last_reported = orm.DateTimeField(null=True)
    reports_count = orm.IntegerField(default=0)

    def self_update(self):
        q = Report.select(Report.reported).where(Report.state==self.id)
        self.reports_count = q.count()
        latest = q.order_by(Report.reported.desc()).limit(1).first()
        self.last_reported = latest and latest.reported

class Company(OrmModel):
    company = orm.CharField(max_length=512, index=True)
    state = orm.CharField(max_length=2, index=True)

    @classmethod
    def select_for_reduce(cls):
        q = cls.select(Report, cls)
        q = q.join_from(cls, Report, orm.JOIN['LEFT_OUTER'], on=(
            (cls.company == Report.company) &
            (cls.state == Report.state)))
        q = q.order_by(cls.state, cls.company)
        return q

    class Meta:
        indexes = [(('company', 'state'), True)]

class Naics(OrmModel):
    id = orm.IntegerField(primary_key=True)
    code = orm.CharField(max_length=32, index=True)
    title = orm.CharField(max_length=255, index=True)

    @classmethod
    def select_for_reduce(cls):
        q = cls.select(NaicsReport, Report, cls)
        q = q.join_from(cls, NaicsReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(NaicsReport, Report, orm.JOIN['LEFT_OUTER'])
        q = q.order_by(cls.id)
        return q

class NaicsReport(OrmModel):
    naics = orm.ForeignKeyField(Naics, on_delete='CASCADE')
    report = orm.ForeignKeyField(Report, on_delete='CASCADE')

    class Meta:
        indexes = [(('naics', 'report'), True)]

class Artifact(OrmModel):
    id = orm.UUIDField(primary_key=True)
    path = orm.CharField(max_length=2083, unique=True)
    url = orm.CharField(max_length=2083)
    created = orm.DateTimeField(index=True, default=utils.now)
    modified = orm.DateTimeField(index=True, default=utils.now)
    mimetype = orm.CharField(max_length=255)
    size = orm.BigIntegerField()
    sha1 = orm.CharField(max_length=40)

    @property
    def name(self):
        return Path(self.path).name

    @classmethod
    def select_for_reduce(cls):
        q = cls.select(ArtifactReport, Report, cls)
        q = q.join_from(cls, ArtifactReport, orm.JOIN['LEFT_OUTER'])
        q = q.join_from(ArtifactReport, Report, orm.JOIN['LEFT_OUTER'])
        q = q.order_by(cls.id)
        return q

    def self_update(self) -> None:
        file = Path(settings.ARTIFACTS_DIR, self.path)
        with file.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha1')
        stat = file.stat()
        self.size = stat.st_size
        self.modified = datetime.fromtimestamp(stat.st_mtime)
        self.mimetype = utils.get_mimetype(file)
        self.sha1 = digest.hexdigest()

class ArtifactReport(OrmModel):
    artifact = orm.ForeignKeyField(Artifact, on_delete='CASCADE')
    report = orm.ForeignKeyField(Report, on_delete='CASCADE')

    class Meta:
        indexes = [(('artifact', 'report'), True)]

# ----------------------------

__all__ += [
    'ArtifactData',
    'ArtifactDetail',
    'CompanyDetail',
    'CompanyName',
    'DataModel',
    'DM',
    'Limit',
    'NaicsData',
    'NaicsDetail',
    'Offset',
    'PageNumber',
    'ReportData',
    'StateCode',
    'StateDetail',
    'ValidationError']

DM = TypeVar('DM', bound='DataModel')
OM = TypeVar('OM', bound=OrmModel)
Limit = Annotated[NonNegativeInt, Le(1000)]
Offset: TypeAlias = NonNegativeInt
PageNumber: TypeAlias = PositiveInt
CompanyName = Annotated[str, StringConstraints(min_length=1)]
StateCode = Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)]

def tzreplace(dt: datetime|None, tzinfo: ZoneInfo) -> datetime|None:
    return dt and dt.replace(hour=0, tzinfo=tzinfo)

class DataModel(DataModel):

    def as_doc(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)

class MapReducingModel(DataModel, Generic[OM]):
    orm_model: ClassVar[type[OM]]

    @classmethod
    def map_reduce(cls, it: Iterable[OM]|None = None) -> Iterator[Self]:
        if it is None:
            it = cls.orm_model.select_for_reduce()
        inst: Self|None = None
        for obj in it:
            if inst is None or not inst.equals_obj(obj):
                if inst:
                    yield inst
                inst = cls.model_validate(obj)
                memo = defaultdict(set)
            inst.reduce_obj(obj, memo)
        if inst:
            yield inst

    def equals_obj(self, obj: OM) -> bool:
        return self.id == obj.id

    @abstractmethod
    def reduce_obj(self, obj: OM, memo: dict[str, set]) -> None: ...

class ReportData(MapReducingModel[Report]):
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
    artifacts: list[ArtifactData] = Field(default_factory=list)
    orm_model: ClassVar = Report
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    def reduce_obj(self, obj: Report, memo: dict[str, set]) -> None:
        nr: NaicsReport|None = getattr(obj, 'naicsreport', None)
        if nr and nr.naics not in memo['naics']:
            naics = NaicsData.model_validate(nr.naics)
            self.naics.append(naics)
            memo['naics'].add(nr.naics)
        ar: ArtifactReport|None = getattr(obj, 'artifactreport', None)
        if ar and ar.artifact not in memo['artifacts']:
            artifact = ArtifactData.model_validate(ar.artifact)
            self.artifacts.append(artifact)
            memo['artifacts'].add(ar.artifact)

    @field_serializer('reported', 'starting')
    def tzreplace(self, dt: datetime|None, _info=None) -> datetime|None:
        return tzreplace(dt, zoneinfos[self.state])

class ArtifactData(DataModel):
    id: UUID = Field(alias='_id')
    url: str
    name: str
    size: int
    media_type: str = Field(alias='mimetype')
    sha1: str
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class ArtifactDetail(ArtifactData, MapReducingModel[Artifact]):
    path: str
    reports_count: int = 0
    orm_model: ClassVar = Artifact

    def reduce_obj(self, obj, memo) -> None:
        ar: ArtifactReport|None = getattr(obj, 'artifactreport', None)
        if ar and ar.report not in memo['reports']:
            self.reports_count += 1
            memo['reports'].add(ar.report)

class NaicsData(DataModel):
    id: int
    code: str
    title: str
    model_config = ConfigDict(from_attributes=True)

class NaicsDetail(NaicsData, MapReducingModel[Naics]):
    reports_count: int = 0
    orm_model: ClassVar = Naics

    def reduce_obj(self, obj, memo) -> None:
        nr: NaicsReport|None = getattr(obj, 'naicsreport', None)
        if nr and nr.report not in memo['reports']:
            self.reports_count += 1
            memo['reports'].add(nr.report)

class StateDetail(DataModel):
    state: StateCode = Field(alias='id')
    last_reported: datetime|None = None
    reports_count: int = 0
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    tzreplace = field_serializer('last_reported')(ReportData.tzreplace)

class CompanyDetail(MapReducingModel[Company]):
    company: str
    state: StateCode
    reports_count: int = 0
    last_reported: datetime|None = None
    orm_model: ClassVar = Company
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    tzreplace = field_serializer('last_reported')(ReportData.tzreplace)

    def reduce_obj(self, obj, memo):
        report: Report = getattr(obj, 'report', None)
        if report and report not in memo['reports']:
            self.reports_count += 1
            self.last_reported = max(filter(None, (self.last_reported, report.reported)))
            memo['reports'].add(report)

    def equals_obj(self, obj):
        return self.state == obj.state and self.company == obj.company


# ----------------------------

__all__ += [
    'FilterModel',
    'ReportsFilter',
    'NaicsFilter',
    'StatesFilter',
    'CompaniesFilter',
    'ArtifactsFilter']

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

class CompaniesFilter(FilterModel[CompanyDetail]):
    text: str|None = None
    company: CompanyName|None = None
    state: StateCode|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    last_reported_after: datetime|None = None
    last_reported_before: datetime|None = None
    result_model: ClassVar = CompanyDetail
    order_fields: ClassVar = {'company', 'state', 'reports_count', 'last_reported'}
    default_ordering: ClassVar = [('company', 1), ('state', 1)]

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

class ArtifactsFilter(FilterModel[ArtifactDetail]):
    id: UUID|None = None
    sha1: str|None = None
    name: str|None = None
    result_model: ClassVar = ArtifactDetail
    order_fields: ClassVar = {'name'}
    default_ordering: ClassVar = [('name', 1)]

# ----------------------------

def migrate() -> None:
    with db.atomic():
        db.create_tables([Report, Company, StateStat, Naics, NaicsReport, Artifact, ArtifactReport])
    if not Naics.select().count():
        load_naics()

def load_naics() -> None:
    logger.info(f'Loading NAICS')
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

actions = dict(migrate=migrate, naics=load_naics)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)

    def run(self):
        actions[self.opts.action]()

if __name__ == '__main__':
    Command.main()
