from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from datetime import datetime
from itertools import batched
from pathlib import Path
from typing import (TYPE_CHECKING, Annotated, Any, ClassVar, Generic, Iterable,
                    Iterator, Literal, Self, TypeAlias, TypeVar)
from uuid import UUID, uuid4, uuid5
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
from .ref import normls
from .ref.tz import zoneinfos

if TYPE_CHECKING:
    from typing import overload

DM = TypeVar('DM', bound='DataModel')
OM = TypeVar('OM', bound='OrmModel')
logger = utils.get_logger('models')

__all__ = [
    'Artifact',
    'ArtifactReport',
    'Company',
    'db',
    'IntegrityError',
    'Naics',
    'NaicsReport',
    'orm',
    'Report',
    'StateStat']

db: orm.Database = db_url.connect(settings.DB_URL)

LEFT_OUTER = orm.JOIN['LEFT_OUTER']

class ModelSelect(orm.ModelSelect, Generic[OM]):
    if TYPE_CHECKING:
        @overload
        def join(self, *args, **kw) -> Self: ...
        @overload
        def join(self, *args) -> Self: ...
        @overload
        def where(self, *args) -> Self: ...
        @overload
        def limit(self, value=None) -> Self: ...
        @overload
        def first(self) -> OM|None: ...
        @overload
        def switch(self, ctx=None) -> Self: ...
        @overload
        def order_by(self, *values) -> Self: ...
        @overload
        def __iter__(self) -> Iterator[OM]: ...

class OrmModel(orm.Model):
    class Meta:
        database = db

    @classmethod
    def select_for_reduce(cls) -> ModelSelect[Self]:
        return cls.select()

    if TYPE_CHECKING:
        DoesNotExist: type[orm.DoesNotExist]
        @overload
        @classmethod
        def select(cls, *args) -> ModelSelect[Self]: ...
        @overload
        @classmethod
        def alias(cls, alias=None) -> type[Self]: ...
        @overload
        @classmethod
        def get(cls, *queries, **filters) -> Self: ...

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
    company_norm = orm.CharField(max_length=512, index=True)

    @classmethod
    def select_for_reduce(cls):
        return (cls
            .select(
                cls,
                CompanyReport := cls.alias(),
                NaicsReport,
                Naics,
                ArtifactReport,
                Artifact)
            .join(
                CompanyReport,
                attr='company_report',
                on=(cls.company_norm == CompanyReport.company_norm))
            .join(NaicsReport, LEFT_OUTER)
            .join(Naics, LEFT_OUTER)
            .switch(cls)
            .join(ArtifactReport, LEFT_OUTER)
            .join(Artifact, LEFT_OUTER)
            .order_by(cls.id, Naics.code, Artifact.id))

class StateStat(OrmModel):
    id = orm.CharField(max_length=2, primary_key=True)
    last_reported = orm.DateTimeField(null=True)
    reports_count = orm.IntegerField(default=0)

    def self_update(self):
        q = Report.select(Report.reported).where(Report.state == self.id)
        self.reports_count = q.count()
        latest = q.order_by(Report.reported.desc()).limit(1).first()
        self.last_reported = latest and latest.reported

class Company(OrmModel):
    NS = uuid5(settings.NAMESPACE, 'Company')
    id = orm.UUIDField(primary_key=True)
    name = orm.CharField(max_length=512, unique=True)
    name_norm = orm.CharField(max_length=512, index=True)
    name_canon = orm.CharField(max_length=512, index=True)

    @classmethod
    def select_for_reduce(cls):
        return (cls
            .select(
                cls,
                Report,
                NaicsReport,
                Naics)
            .join(
                Report,
                LEFT_OUTER,
                on=(Report.company_norm == cls.name_norm))
            .join(NaicsReport, LEFT_OUTER)
            .join(Naics, LEFT_OUTER)
            .order_by(cls.name_norm, cls.name, Report.state, Naics.id))

class Naics(OrmModel):
    id = orm.IntegerField(primary_key=True)
    code = orm.CharField(max_length=32, index=True)
    title = orm.CharField(max_length=255, index=True)

    @classmethod
    def select_for_reduce(cls):
        return (cls
            .select(NaicsReport, Report, cls)
            .join(NaicsReport, LEFT_OUTER)
            .join(Report, LEFT_OUTER)
            .join(Company, LEFT_OUTER, on=(Report.company_norm == Company.name_norm))
            .order_by(cls.id))

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
        return (cls
            .select(cls, ArtifactReport, Report)
            .join(ArtifactReport, LEFT_OUTER)
            .join(Report, LEFT_OUTER)
            .order_by(cls.id))

    def self_update(self) -> None:
        file = Path(settings.ARTIFACTS_DIR, self.path)
        with file.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha1')
        stat = file.stat()
        data = dict(
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime),
            mimetype=utils.get_mimetype(file),
            sha1=digest.hexdigest())
        for field, value in data.items():
            if getattr(self, field) != value:
                setattr(self, field, value)

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
            it = cls.orm_model.select_for_reduce().iterator()
        inst: Self|None = None
        for obj in it:
            if inst is None or not inst.equals_obj(obj):
                if inst:
                    inst.reduce_end(memo)
                    yield inst
                inst = cls.model_validate(obj)
                memo = defaultdict(set)
            inst.reduce_obj(obj, memo)
        if inst:
            inst.reduce_end(memo)
            yield inst

    def equals_obj(self, obj: OM) -> bool:
        return self.id == obj.id

    def reduce_obj(self, obj: OM, memo: dict[str, set]) -> None:
        pass

    def reduce_end(self, memo: dict[str, set]) -> None:
        pass

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
        nr: NaicsReport|None = getattr(obj.company_report, 'naicsreport', None)
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
    created: datetime
    modified: datetime
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
    companies_count: int = 0
    employees_sum: int = 0
    orm_model: ClassVar = Naics

    def reduce_obj(self, obj, memo) -> None:
        nr: NaicsReport|None = getattr(obj, 'naicsreport', None)
        if nr and nr.report not in memo['reports']:
            self.reports_count += 1
            if nr.report.employees:
                self.employees_sum += nr.report.employees
            memo['reports'].add(nr.report)
            company: str|None = getattr(nr.report, 'company_norm', None)
            if company and company not in memo['companies']:
                self.companies_count += 1
                memo['companies'].add(company)

class StateDetail(MapReducingModel[StateStat]):
    id: StateCode
    last_reported: datetime|None = None
    reports_count: int = 0
    orm_model: ClassVar = StateStat
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class CompanyDetail(MapReducingModel[Company]):
    id: UUID = Field(alias='_id')
    name: CompanyName
    aliases: list[CompanyName] = Field(default_factory=list)
    states: list[StateCode] = Field(default_factory=list)
    naics: list[NaicsData] = Field(default_factory=list)
    reports_count: int = 0
    last_reported: datetime|None = None
    employees_sum: int = 0
    orm_model: ClassVar = Company
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    def reduce_obj(self, obj, memo):
        memo['canon'].add(obj.name_canon)
        if obj.name_canon not in memo['aliases']:
            self.aliases.append(obj.name_canon)
            memo['aliases'].add(obj.name)
        if obj.name not in memo['aliases']:
            self.aliases.append(obj.name)
            memo['aliases'].add(obj.name)
        report: Report = getattr(obj, 'report', None)
        if report and report not in memo['reports']:
            self.reports_count += 1
            if report.employees:
                self.employees_sum += report.employees
            self.last_reported = max(filter(None, (self.last_reported, report.reported)))
            memo['reports'].add(report)
            if report.state not in memo['states']:
                self.states.append(report.state)
                memo['states'].add(report.state)
            nr: NaicsReport|None = getattr(report, 'naicsreport', None)
            if nr and nr.naics not in memo['naics']:
                naics = NaicsData.model_validate(nr.naics)
                self.naics.append(naics)
                memo['naics'].add(nr.naics)

    def reduce_end(self, memo):
        self.name = sorted(memo['canon'], key=normls.company_name_sort)[0]
        self.id = uuid5(Company.NS, self.name)

    def equals_obj(self, obj: Company) -> bool:
        return obj.name_norm == normls.company_name_norm(self.name)

# ----------------------------

__all__ += [
    'ArtifactsFilter',
    'CompaniesFilter',
    'FilterModel',
    'NaicsFilter',
    'ReportsFilter',
    'StatesFilter']

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
    id: StateCode|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    last_reported_after: datetime|None = None
    last_reported_before: datetime|None = None
    result_model: ClassVar = StateDetail
    order_fields: ClassVar = {'id', 'reports_count', 'last_reported'}
    default_ordering: ClassVar = [('id', 1)]

class CompaniesFilter(FilterModel[CompanyDetail]):
    id: UUID|None = None
    text: str|None = None
    name: CompanyName|None = None
    state: StateCode|None = None
    naics: int|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    employees_sum_gt: int|None = None
    employees_sum_lt: int|None = None
    last_reported_after: datetime|None = None
    last_reported_before: datetime|None = None
    result_model: ClassVar = CompanyDetail
    order_fields: ClassVar = {'name', 'reports_count', 'last_reported', 'employees_sum'}
    default_ordering: ClassVar = [('name', 1)]

class NaicsFilter(FilterModel[NaicsDetail]):
    id: int|None = None
    code: int|None = None
    prefix: int|None = None
    title: str|None = None
    reports_count_gt: int|None = None
    reports_count_lt: int|None = None
    companies_count_gt: int|None = None
    companies_count_lt: int|None = None
    employees_sum_gt: int|None = None
    employees_sum_lt: int|None = None
    result_model: ClassVar = NaicsDetail
    order_fields: ClassVar = {'id', 'code', 'title', 'reports_count', 'companies_count'}
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
    import playhouse.migrate
    if isinstance(db, orm.SqliteDatabase):
        migrator = playhouse.migrate.SqliteMigrator(db)
    else:
        migrator = playhouse.migrate.PostgresqlMigrator(db)
    with db.atomic():

        tables = set(db.get_tables())

        if 'company' in tables:
            cols = {col.name: col for col in db.get_columns('company')}
            idxs = {idx.name: idx for idx in db.get_indexes('company')}
            needed = (
                'state' in cols or
                'company' in cols or
                'name_norm' not in cols or
                'name_canon' not in cols or
                'company_name_norm' not in idxs or
                idxs['company_name_norm'].unique or
                cols['id'].data_type != 'uuid')
            if needed:
                logger.info(f'Migrating company table')
                tmp = f'company_tmp_{uuid4().hex[:8]}'
                db.execute_sql(f'DROP TABLE IF EXISTS {tmp}')
                db.execute_sql(f'ALTER TABLE company RENAME to {tmp}')
                db.create_tables([Company])
                col = 'company' if 'company' in cols else 'name'
                cur = db.execute_sql(f'SELECT {col} FROM {tmp}')
                if cur.rowcount:
                    def vals(name: str):
                        return (
                            uuid5(Company.NS, name),
                            name,
                            normls.company_name_norm(name),
                            normls.company_name_canon(name))
                    q = (
                        Company
                        .insert_from(
                            (vals(x[0]) for x in cur),
                            ['id', 'name', 'name_norm', 'name_canon'])
                        .on_conflict('IGNORE'))
                    q.execute()
                db.execute_sql(f'DROP TABLE {tmp}')

        if 'report' in tables:
            cols = {col.name: col for col in db.get_columns('report')}
            needed = 'company_norm' not in cols
            if needed:
                logger.info(f'Migrating report table')
                field = orm.CharField(max_length=512, default='', index=True)
                op = migrator.add_column('report', 'company_norm', field)
                playhouse.migrate.migrate(op)
                for batch in batched(Report.select(Report.id, Report.company), 1000):
                    reports = list(batch)
                    for report in reports:
                        report.company_norm = normls.company_name_norm(report.company)
                    Report.bulk_update(reports, ['company_norm'])

        db.create_tables([
            Company,
            Report,
            StateStat,
            Naics,
            NaicsReport,
            Artifact,
            ArtifactReport])

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
