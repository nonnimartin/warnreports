from __future__ import annotations

import dataclasses
import logging
import re
from datetime import datetime, timezone
from typing import Annotated, Any, Callable, ClassVar, Iterator, Literal, Self
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from annotated_types import Gt, Le, Lt
from pydantic import (BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl,
                      NonNegativeFloat, NonNegativeInt, PlainSerializer,
                      PositiveInt, StringConstraints, TypeAdapter,
                      field_serializer, model_validator)
from pydantic_core import ValidationError as ValidationError

from . import Stage, settings, utils
from .ref.tz import zoneinfos

logger = logging.getLogger(__name__)

__all__ = [
    'ArtifactData',
    'ArtifactDetail',
    'ClassVar',
    'CompanyDetail',
    'CompanyName',
    'DataModel',
    'NaicsData',
    'NaicsDetail',
    'NaicsId',
    'NaicsRootId',
    'ReportData',
    'StateCode',
    'StateDetail',
    'ValidationError',
    'ValidStateCode']

UrlType = Annotated[
    HttpUrl,
    PlainSerializer(str, return_type=str)]
CompanyName = Annotated[
    str,
    StringConstraints(min_length=1),
    Field(description='The company name')]
StateCode = Annotated[
    str,
    StringConstraints(min_length=2, max_length=2, to_upper=True, pattern=re.compile(r'^[A-Z]{2}$', re.I)),
    Field(description='The 2-letter state postal code')]
NaicsId = Annotated[
    int,
    Gt(10),
    Lt(1_000_000),
    Field(description='The 2 to 6 digit NAICS code')]
NaicsRootId = Annotated[
    int,
    Gt(10),
    Lt(100),
    Field(description='The root NAICS code')]

ValidStateCode: Callable[[Any], StateCode] = TypeAdapter(StateCode).validate_python

def tzreplace(dt: datetime|None, tzinfo: ZoneInfo) -> datetime|None:
    return dt and dt.replace(hour=0, tzinfo=tzinfo)

def utcreplace(dt: datetime|None) -> datetime|None:
    if dt and not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

class DataModel(BaseModel):
    pass

class ReportData(DataModel):
    id: UUID = Field(alias='_id')
    company: CompanyName
    company_id: UUID = Field(
        default=None,
        title='Company ID',
        description='The internal company ID, for cross-referencing related reports')
    state: StateCode
    location: str|None = Field(
        default=None,
        description='Location details (city, county, address, store number, etc.)')
    reported: datetime = Field(
        description='The indicated date the report was filed')
    starting: datetime|None = Field(
        default=None,
        description='The effective start date')
    employees: NonNegativeInt|None = Field(
        default=None,
        description='The projected number of employees to be affected')
    action: str|None = Field(
        default=None,
        description='The action (layoff, closure, etc.)')
    url: UrlType = Field(
        title='URL',
        description='Source link to the report or state agency')
    naics: list[NaicsData] = Field(
        default_factory=list,
        description='Associated NAICS details')
    artifacts: list[ArtifactData] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'Report')

    @field_serializer('reported', 'starting')
    def tzreplace(self, dt: datetime|None) -> datetime|None:
        return tzreplace(dt, zoneinfos[self.state])

class ArtifactData(DataModel):
    id: UUID = Field(alias='_id')
    url: UrlType
    name: str
    size: NonNegativeInt
    media_type: str
    sha1: str
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class ArtifactDetail(ArtifactData):
    path: str
    state: StateCode
    reports_count: NonNegativeInt = 0
    created: datetime
    modified: datetime

class NaicsData(DataModel):
    id: NaicsId
    code: str = Field(description='The code string')
    title: str = Field(description='The NAICS industry title')
    parent: NaicsId|None = Field(description='The parent NAICS code, if any')
    depth: NonNegativeInt = Field(description='The tree depth')
    root: NaicsRootId
    is_leaf: bool = Field(description='Whether this is a leaf node', default=False)
    model_config = ConfigDict(from_attributes=True)

class NaicsDetail(NaicsData):
    states: list[StateCode] = Field(default_factory=list)
    reports_count: NonNegativeInt = 0
    companies_count: NonNegativeInt = 0
    employees_sum: NonNegativeInt = 0
    states_count: NonNegativeInt = 0
    last_reported: datetime|None = None
    last_report_state: StateCode|None = None
    last_report_id: UUID|None = None

class StateDetail(DataModel):
    id: StateCode
    last_reported: datetime|None = None
    reports_count: NonNegativeInt = 0
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class CompanyDetail(DataModel):
    id: UUID = Field(alias='_id')
    name: CompanyName
    aliases: list[CompanyName] = Field(default_factory=list)
    states: list[StateCode] = Field(default_factory=list)
    naics: list[NaicsData] = Field(default_factory=list)
    reports_count: NonNegativeInt = 0
    last_reported: datetime|None = None
    last_report_state: StateCode|None = None
    last_report_id: UUID|None = None
    employees_sum: NonNegativeInt = 0
    states_count: NonNegativeInt = 0
    aliases_count: NonNegativeInt = 0
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

# ----------------------------

__all__ += [
    'Extraction',
    'PipelineBatchOpts',
    'PipelineLog',
    'PipelineOpts',
    'PipelineRunError',
    'PipelineRunDetail',
    'ScraperOpts',
    'Translation']

class Extraction(DataModel):
    id: UUID = Field(alias='_id', default=None)
    state: StateCode|None = Field(default=None)
    i: NonNegativeInt|None = Field(default=None)
    data: dict[str, str|None] = Field(default_factory=dict)
    stat_exclude_fields: ClassVar = ('scrape_time', 'NAICS Codes')
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class Translation(DataModel):
    id: UUID = Field(None, alias='_id')
    values_id: UUID = Field(frozen=True)
    state: StateCode = Field(frozen=True)
    company: CompanyName|None = None
    reported: datetime|None = None
    location: str|None = None
    employees: NonNegativeInt|None = None
    starting: datetime|None = None
    action: str|None = None
    url: UrlType|None = None
    industry: str|None = None
    first_scraped: datetime|None = None
    report_id: str|None = None
    naics: list[NaicsId]|None = None
    artifacts: dict[str, UrlType]|None = None
    extraction: Extraction = Field(frozen=True)
    stat_exclude_fields: ClassVar = ('data',)
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        validate_assignment=True,
        revalidate_instances='always')

    tzreplace = field_serializer('reported', 'starting')(ReportData.tzreplace)
    utcreplace = field_serializer('first_scraped')(utcreplace)

class PipelineRunDetail(DataModel):
    state: StateCode
    stage: Stage
    start: datetime|None = None
    end: datetime|None = None
    elapsed: NonNegativeFloat = 0
    failed: bool = False
    error: PipelineRunError|None = None
    result: dict[str, Any]|None = None

    @property
    def ischange(self) -> bool:
        return bool(self.result and not self.result.get('nochange'))

    def sync(self) -> None:
        if self.start:
            until = self.end or utils.utcnow()
            self.elapsed = (until - self.start).total_seconds()

class PipelineRunError(DataModel):
    type: str
    message: str
    state: StateCode|None = None
    stage: Stage|None = None

    @classmethod
    def fromexc(cls, exc: Exception, **kw) -> Self:
        return cls(type=type(exc).__name__, message=str(exc), **kw)

class PipelineBatchOpts(DataModel):
    clean: bool = Field(
        default=False,
        description='Clean each stage before running')
    clean_only: bool = Field(
        default=False,
        description='Only clean, do not run')
    stat_only: bool = Field(
        default=False,
        description='Only show stats, do not run')
    fail: bool = Field(
        default=True,
        description='Fail on error')
    incremental: bool = Field(
        default=False,
        description=(
            'If a stage indicates no change after running, '
            'skip subsequent stages for the state'))
    concurrent: bool = Field(
        default=False,
        description=(
            'Use multiple async workers when applicable. '
            'The load stage is always synchronized with one worker'))
    max_workers: NonNegativeInt = Field(
        default=settings.ETL_DEFAULT_WORKERS,
        description=(
            'Max workers, applicable only when concurrent is specified, '
            f'default ETL_DEFAULT_WORKERS ({settings.ETL_DEFAULT_WORKERS})'))
    max_threads: NonNegativeInt = Field(
        default=settings.ETL_DEFAULT_THREADS,
        description=(
            'Max threads, applicable only when concurrent is specified, '
            f'default ETL_DEFAULT_THREADS ({settings.ETL_DEFAULT_THREADS})'))

    @model_validator(mode='after')
    def check_flags(self) -> Self:
        if self.clean_only and (self.clean or self.incremental or self.stat_only):
            raise ValueError(f'Cannot specify clean_only with clean, incremental, or stat_only')
        if self.stat_only and (self.clean or self.incremental or self.clean_only):
            raise ValueError(f'Cannot specify stat_only with clean, incremental, or clean_only')
        return self

class ScraperOpts(DataModel):
    selenium_max_procs: NonNegativeInt = Field(
        default=settings.SELENIUM_MAX_PROCS,
        description=(
            'Max number of concurrent web drivers if applicable, '
            f'default SELENIUM_MAX_PROCS ({settings.SELENIUM_MAX_PROCS})'))

class PipelineOpts(ScraperOpts):
    lazy: bool = Field(
        default=True,
        description='Use result set iterators for database queries')
    rollback: bool = Field(
        default=False,
        description='Rollback database transactions (dry run)')
    load_per_tick: PositiveInt = Field(
        default=100,
        description='How frequently to asyncio.sleep(0) during load stage')

type UniqueList[T] = Annotated[
    list[T],
    BeforeValidator(lambda value: list(utils.unique(value))),
    Field(default_factory=list)]

class PipelineLog(DataModel):
    id: UUID = Field(alias='_id', default_factory=uuid4)
    stages: UniqueList[Stage]
    states: UniqueList[StateCode]
    context: dict[str, Any] = Field(default_factory=dict)
    batch_opts: PipelineBatchOpts = Field(default_factory=PipelineBatchOpts)
    pipeline_opts: PipelineOpts = Field(default_factory=PipelineOpts)
    start: datetime|None = None
    end: datetime|None = None
    elapsed: NonNegativeFloat = 0.0
    errors: list[PipelineRunError] = Field(default_factory=list)
    runs: list[PipelineRunDetail] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    def sync(self) -> None:
        if self.start:
            until = self.end or utils.utcnow()
            self.elapsed = (until - self.start).total_seconds()
        for run in self.runs:
            run.sync()

    def stageruns(self, stage: Stage):
        for run in self.runs:
            if stage == run.stage:
                yield run
        
    def get_load_changes(self) -> list[dict[str, Any]]:
        body = []
        for run in self.stageruns(Stage.Load):
            if not run.ischange:
                continue
            counts = run.result['counts']
            body.append(dict(
                state=run.state,
                created=counts['create'],
                updated=counts['update']))
        body.sort(key=lambda x: x['state'])
        return body

    def get_scrape_stats(self) -> list[dict[str, Any]]:
        body = []
        for run in self.stageruns(Stage.Scrape):
            metrics = run.result and run.result.get('metrics')
            body.append(dict(
                state=run.state,
                elapsed=run.elapsed,
                request_count=metrics and metrics.get('request_count'),
                request_bytes=metrics and metrics.get('request_bytes')))
        body.sort(key=lambda x: x['elapsed'], reverse=True)
        return body

    def get_runs(self) -> list[dict[str, Any]]:
        return [
            dict(
                stage=run.stage[0].upper(),
                state=run.state,
                elapsed=run.elapsed,
                failed=run.failed if run.end else None,
                nochange=run.result and run.result.get('nochange'))
            for run in self.runs]

    def get_running(self) -> list[dict[str, Any]]:
        runs = [
            run for run in self.get_runs()
            if run['failed'] in (True, None)]
        for run in runs:
            run.pop('nochange', None)
        return runs

    def get_short(self) -> dict[str, Any]:
        mapping = dict(
            id=str(self.id),
            start=self.start and self.start.isoformat(timespec='seconds'),
            end=self.end and self.end.isoformat(timespec='seconds'),
            stages=''.join(s[0].upper() for s in self.stages),
            states=len(self.states),
            runs=len(self.runs),
            elapsed=self.elapsed)
        if self.errors:
            mapping.update(errors=len(self.errors))
        for key, value in self.batch_opts.model_dump().items():
            if value is True:
                mapping[key] = value
        for key, value in self.context.items():
            if value:
                mapping[f'context.{key}'] = value
        return mapping

# ----------------------------

__all__ += ['FilterModel', 'Limit', 'Offset']

type Limit = Annotated[NonNegativeInt, Le(1_000)]
type Offset = NonNegativeInt

class FilterModel[DM: DataModel](DataModel):
    order: str|None = None
    result_model: ClassVar[type[DM]]
    order_fields: ClassVar[set[str]] = set()
    default_ordering: ClassVar[list[OrderItem]] = []

    def get_orders(self) -> list[OrderItem]:
        if self.order:
            orders = list(parse_orders(self.order, self.order_fields))
        else:
            orders = list(self.default_ordering)
        if ('_id', 1) not in orders and ('_id', -1) not in orders:
            orders.append(('_id', 1))
        return orders

def parse_orders(order: str, allowed: set[str]|None = None) -> Iterator[OrderItem]:
    for field in filter(None, re.split(r',\s*', order)):
        if field.startswith('-'):
            field = field[1:]
            dir_ = -1
        else:
            dir_ = 1
        if allowed is None or field in allowed:
            yield field, dir_

def ensurelist[T](value: T|list[T]|None) -> list[T]|None:
    if isinstance(value, list):  
        return value
    if value is not None:
        return [value]

type OrderItem = tuple[str, Literal[1, -1]]
type AsList[T] = Annotated[list[T]|None, BeforeValidator(ensurelist)]


@dataclasses.dataclass
class Fi:
    oper: str
    alias: str|None = None

    def __post_init__(self):
        if self.oper == '$search':
            if self.alias:
                raise ValueError(f'alias {self.alias} for oper {self.oper}')
            self.alias = '$text'

# ----------------------------

__all__ += [
    'ArtifactsFilter',
    'CompaniesFilter',
    'NaicsFilter',
    'ReportsFilter',
    'StatesFilter']

class ReportsFilter(FilterModel[ReportData]):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    id_not: Annotated[AsList[UUID], Fi('$nin', '_id')] = None
    text: Annotated[str|None, Fi('$search')] = None
    company: Annotated[AsList[CompanyName], Fi('$in')] = None
    company_id: Annotated[AsList[UUID], Fi('$in')] = None
    state: Annotated[AsList[StateCode], Fi('$in')] = None
    location: Annotated[str|None, Fi('$contains')] = None
    action: Annotated[str|None, Fi('$contains')] = None
    naics: Annotated[AsList[NaicsId], Fi('$naics')] = None
    reported_min: Annotated[datetime|None, Fi('$gte', 'reported')] = None
    reported_max: Annotated[datetime|None, Fi('$lte', 'reported')] = None
    starting_min: Annotated[datetime|None, Fi('$gte', 'starting')] = None
    starting_max: Annotated[datetime|None, Fi('$lte', 'starting')] = None
    employees_min: Annotated[NonNegativeInt|None, Fi('$gte', 'employees')] = None
    employees_max: Annotated[NonNegativeInt|None, Fi('$lte', 'employees')] = None
    order_fields: ClassVar = {
        'reported', 'company', 'state', 'employees', 'starting', 'action'}
    default_ordering: ClassVar = [('reported', -1), ('company', 1), ('state', 1)]
    result_model: ClassVar = ReportData

class NaicsStatesFilterMixin:
    reports_count_min: Annotated[NonNegativeInt|None, Fi('$gte', 'reports_count')] = None
    reports_count_max: Annotated[NonNegativeInt|None, Fi('$lte', 'reports_count')] = None
    last_reported_min: Annotated[datetime|None, Fi('$gte', 'last_reported')] = None
    last_reported_max: Annotated[datetime|None, Fi('$lte', 'last_reported')] = None

class StatesFilter(FilterModel[StateDetail], NaicsStatesFilterMixin):
    id: Annotated[AsList[StateCode], Fi('$in')] = None
    result_model: ClassVar = StateDetail
    order_fields: ClassVar = {'id', 'reports_count', 'last_reported'}
    default_ordering: ClassVar = [('id', 1)]

class NaicsCompaniesFilterMixin(NaicsStatesFilterMixin):
    state: Annotated[AsList[StateCode], Fi('$in', 'states')] = None
    states_count_min: Annotated[NonNegativeInt|None, Fi('$gte', 'states_count')] = None
    states_count_max: Annotated[NonNegativeInt|None, Fi('$lte', 'states_count')] = None
    employees_sum_min: Annotated[NonNegativeInt|None, Fi('$gte', 'employees_sum')] = None
    employees_sum_max: Annotated[NonNegativeInt|None, Fi('$lte', 'employees_sum')] = None

class CompaniesFilter(FilterModel[CompanyDetail], NaicsCompaniesFilterMixin):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    text: Annotated[str|None, Fi('$search')] = None
    name: Annotated[AsList[CompanyName], Fi('$in', 'aliases')] = None
    naics: Annotated[AsList[NaicsId], Fi('$naics')] = None
    aliases_count_min: Annotated[NonNegativeInt|None, Fi('$gte', 'aliases_count')] = None
    aliases_count_max: Annotated[NonNegativeInt|None, Fi('$lte', 'aliases_count')] = None
    order_fields: ClassVar = (
        {'name', 'aliases_count'} |
        {'reports_count', 'states_count', 'last_reported', 'employees_sum'})
    default_ordering: ClassVar = [('name', 1)]
    result_model: ClassVar = CompanyDetail

class NaicsFilter(FilterModel[NaicsDetail], NaicsCompaniesFilterMixin):
    id: Annotated[AsList[NaicsId], Fi('$in')] = None
    prefix: Annotated[AsList[NaicsId], Fi('$naics', '')] = None
    title: Annotated[str|None, Fi('$contains')] = None
    root: Annotated[AsList[NaicsRootId], Fi('$in')] = None
    parent: Annotated[AsList[NaicsId], Fi('$in')] = None
    is_leaf: Annotated[bool|None, Fi('$eq')] = None
    includes: AsList[NaicsId] = None
    depth_min: Annotated[NonNegativeInt|None, Fi('$gte', 'depth')] = None
    depth_max: Annotated[NonNegativeInt|None, Fi('$lte', 'depth')] = None
    companies_count_min: Annotated[NonNegativeInt|None, Fi('$gte', 'companies_count')] = None
    companies_count_max: Annotated[NonNegativeInt|None, Fi('$lte', 'companies_count')] = None
    order_fields: ClassVar = (
        {'id', 'code', 'title', 'root', 'depth', 'companies_count'} |
        {'reports_count', 'states_count', 'last_reported', 'employees_sum'})
    default_ordering: ClassVar = [('code', 1), ('id', 1)]
    result_model: ClassVar = NaicsDetail

class ArtifactsFilter(FilterModel[ArtifactDetail]):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    state: Annotated[AsList[StateCode], Fi('$in')] = None
    sha1: Annotated[str|None, Fi('$eq')] = None
    name: Annotated[str|None, Fi('$eq')] = None
    order_fields: ClassVar = {'name'}
    default_ordering: ClassVar = [('name', 1)]
    result_model: ClassVar = ArtifactDetail

# ----------------------------

__all__ += [
    'ExtractionFilter',
    'PipelineLogFilter',
    'TranslationFilter']

class ExtractionFilter(FilterModel[Extraction]):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    state: Annotated[AsList[StateCode], Fi('$in')] = None
    i_min: Annotated[NonNegativeInt|None, Fi('$gte')] = None
    i_max: Annotated[NonNegativeInt|None, Fi('$lte')] = None
    default_ordering: ClassVar = [('state', 1), ('i', 1)]
    result_model: ClassVar = Extraction

class TranslationFilter(FilterModel[Translation]):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    state: Annotated[AsList[StateCode], Fi('$in')] = None
    default_ordering: ClassVar = [('_id', 1)]
    result_model: ClassVar = Translation

class PipelineLogFilter(FilterModel[PipelineLog]):
    id: Annotated[AsList[UUID], Fi('$in', '_id')] = None
    stages: Annotated[AsList[Stage], Fi('$in')] = None
    state: Annotated[AsList[StateCode], Fi('$in', 'states')] = None
    start_min: Annotated[datetime|None, Fi('$gte', 'start')] = None
    start_max: Annotated[datetime|None, Fi('$lte', 'start')] = None
    end_min: Annotated[datetime|None, Fi('$gte', 'end')] = None
    end_max: Annotated[datetime|None, Fi('$lte', 'end')] = None
    elapsed_min: Annotated[NonNegativeFloat|None, Fi('$gte', 'elapsed')] = None
    elapsed_max: Annotated[NonNegativeFloat|None, Fi('$lte', 'elapsed')] = None
    default_ordering: ClassVar = [('start', -1)]
    order_fields: ClassVar = {'start', 'end'}
    result_model: ClassVar = PipelineLog
