from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal, Self, TypeAlias
from uuid import UUID
from zoneinfo import ZoneInfo

from annotated_types import Le
from pydantic import BaseModel as DataModel
from pydantic import (ConfigDict, Field, NonNegativeInt, StringConstraints,
                      field_serializer, model_validator)
from pydantic_core import ValidationError as ValidationError

from . import Stage, settings, utils
from .ref.tz import zoneinfos

logger = utils.get_logger('models')

__all__ = [
    'ArtifactData',
    'ArtifactDetail',
    'ClassVar',
    'CompanyDetail',
    'CompanyName',
    'DataModel',
    'Limit',
    'NaicsData',
    'NaicsDetail',
    'Offset',
    'ReportData',
    'StateCode',
    'StateDetail',
    'ValidationError']

Limit = Annotated[NonNegativeInt, Le(1000)]
Offset: TypeAlias = NonNegativeInt
CompanyName = Annotated[str, StringConstraints(min_length=1)]
StateCode = Annotated[str, StringConstraints(min_length=2, max_length=2, to_upper=True)]

def tzreplace(dt: datetime|None, tzinfo: ZoneInfo) -> datetime|None:
    return dt and dt.replace(hour=0, tzinfo=tzinfo)

class DataModel(DataModel):

    def as_doc(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)

class ReportData(DataModel):
    id: UUID = Field(alias='_id')
    company: CompanyName = Field(
        description='The company name as indicated')
    company_id: UUID = Field(
        default=None,
        title='Company ID',
        description='The internal company ID, for cross-referencing related reports')
    state: StateCode = Field(
        description='The 2-letter state postal code')
    location: str|None = Field(
        default=None,
        description='Location details (city, county, address, store number, etc.)')
    reported: datetime = Field(
        description='The indicated date the report was filed')
    starting: datetime|None = Field(
        default=None,
        description='The effective start date')
    employees: int|None = Field(
        default=None,
        description='The projected number of employees to be affected')
    action: str|None = Field(
        default=None,
        description='The action (layoff, closure, etc.)')
    url: str = Field(
        title='URL',
        description='Source link to the report or state agency')
    naics: list[NaicsData] = Field(
        default_factory=list,
        description='Associated NAICS details')
    artifacts: list[ArtifactData] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    @field_serializer('reported', 'starting')
    def tzreplace(self, dt: datetime|None, _info=None) -> datetime|None:
        return tzreplace(dt, zoneinfos[self.state])

class ArtifactData(DataModel):
    id: UUID = Field(alias='_id')
    url: str
    name: str
    size: int
    media_type: str
    sha1: str
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class ArtifactDetail(ArtifactData):
    path: str
    reports_count: int = 0
    created: datetime
    modified: datetime

class NaicsData(DataModel):
    id: int = Field(description='The 2 to 6 digit NAICS code')
    code: str = Field(description='The code string')
    title: str = Field(description='The NAICS industry title')
    parent: int|None = Field(description='The parent NAICS code, if any')
    depth: int = Field(description='The tree depth')
    root: int = Field(description='The root NAICS code')
    is_leaf: bool = Field(description='Whether this is a leaf node', default=False)
    model_config = ConfigDict(from_attributes=True)

class NaicsDetail(NaicsData):
    states: list[StateCode] = Field(default_factory=list)
    reports_count: int = 0
    companies_count: int = 0
    employees_sum: int = 0
    states_count: int = 0
    last_reported: datetime|None = None
    last_report_state: StateCode|None = None
    last_report_id: UUID|None = None

class StateDetail(DataModel):
    id: StateCode
    last_reported: datetime|None = None
    reports_count: int = 0
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

class CompanyDetail(DataModel):
    id: UUID = Field(alias='_id')
    name: CompanyName
    aliases: list[CompanyName] = Field(default_factory=list)
    states: list[StateCode] = Field(default_factory=list)
    naics: list[NaicsData] = Field(default_factory=list)
    reports_count: int = 0
    last_reported: datetime|None = None
    last_report_state: StateCode|None = None
    last_report_id: UUID|None = None
    employees_sum: int = 0
    states_count: int = 0
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

# ----------------------------

__all__ += [
    'ArtifactsFilter',
    'CompaniesFilter',
    'FilterModel',
    'NaicsFilter',
    'ReportsFilter',
    'StatesFilter']

class FilterModel[DM: DataModel](DataModel):
    order: str|None = None
    result_model: ClassVar[type[DM]]
    order_fields: ClassVar[set[str]] = set()
    default_ordering: ClassVar[list[tuple[str, Literal[1, -1]]]] = []

    def get_ordering(self):
        if self.order:
            yield from self.parse_ordering(self.order, self.order_fields)
        else:
            yield from self.default_ordering

    @classmethod
    def parse_ordering(cls, order: str, allowed: set[str]|None = None):
        for field in filter(None, re.split(r',\s*', order)):
            if field.startswith('-'):
                field = field[1:]
                dir_ = -1
            else:
                dir_ = 1
            if allowed is None or field in allowed:
                yield field, dir_

class ReportsFilter(FilterModel[ReportData]):
    id: list[UUID]|None = None
    id_not: list[UUID]|None = None
    text: str|None = None
    company: list[CompanyName]|None = None
    company_id: list[UUID]|None = None
    state: list[StateCode]|None = None
    location: str|None = None
    action: str|None = None
    naics: list[int]|None = None
    reported_min: datetime|None = None
    reported_max: datetime|None = None
    starting_min: datetime|None = None
    starting_max: datetime|None = None
    employees_min: int|None = None
    employees_max: int|None = None
    result_model: ClassVar = ReportData
    order_fields: ClassVar = {'reported', 'company', 'state', 'employees', 'starting', 'action'}
    default_ordering: ClassVar = [('reported', -1), ('company', 1), ('state', 1)]

class NaicsStatesFilterMixin:
    reports_count_min: int|None = None
    reports_count_max: int|None = None
    last_reported_min: datetime|None = None
    last_reported_max: datetime|None = None

class StatesFilter(FilterModel[StateDetail], NaicsStatesFilterMixin):
    id: list[StateCode]|None = None
    result_model: ClassVar = StateDetail
    order_fields: ClassVar = {'id', 'reports_count', 'last_reported'}
    default_ordering: ClassVar = [('id', 1)]

class NaicsCompaniesFilterMixin(NaicsStatesFilterMixin):
    state: list[StateCode]|None = None
    states_count_min: int|None = None
    states_count_max: int|None = None
    employees_sum_min: int|None = None
    employees_sum_max: int|None = None

class CompaniesFilter(FilterModel[CompanyDetail], NaicsCompaniesFilterMixin):
    id: list[UUID]|None = None
    text: str|None = None
    name: list[CompanyName]|None = None
    naics: list[int]|None = None
    result_model: ClassVar = CompanyDetail
    order_fields: ClassVar = {'name', 'reports_count', 'states_count', 'last_reported', 'employees_sum'}
    default_ordering: ClassVar = [('name', 1)]

class NaicsFilter(FilterModel[NaicsDetail], NaicsCompaniesFilterMixin):
    id: list[int]|None = None
    prefix: list[int]|None = None
    title: str|None = None
    root: list[int]|None = None
    parent: list[int]|None = None
    is_leaf: bool|None = None
    includes: list[int]|None = None
    depth_min: int|None = None
    depth_max: int|None = None
    companies_count_min: int|None = None
    companies_count_max: int|None = None
    result_model: ClassVar = NaicsDetail
    order_fields: ClassVar = (
        {'id', 'code', 'title', 'root', 'depth', 'companies_count'} |
        {'reports_count', 'states_count', 'last_reported', 'employees_sum'})
    default_ordering: ClassVar = [('code', 1), ('id', 1)]

class ArtifactsFilter(FilterModel[ArtifactDetail]):
    id: list[UUID]|None = None
    state: list[StateCode]|None = None
    sha1: str|None = None
    name: str|None = None
    result_model: ClassVar = ArtifactDetail
    order_fields: ClassVar = {'name'}
    default_ordering: ClassVar = [('name', 1)]

# ----------------------------

__all__ += [
    'PipelineBatchOpts',
    'PipelineLog',
    'PipelineOpts',
    'PipelineRunError',
    'PipelineRunDetail',
    'ScraperOpts']

class PipelineRunDetail(DataModel):
    state: StateCode
    stage: Stage
    start: datetime|None = None
    end: datetime|None = None
    elapsed: float = 0
    failed: bool = False
    error: PipelineRunError|None = None
    result: dict[str, Any]|None = None

class PipelineRunError(DataModel):
    type: str
    message: str
    state: StateCode|None = None
    stage: Stage|None = None

    @classmethod
    def fromexc(cls, exc: Exception, **kw) -> Self:
        return cls(type=type(exc).__name__, message=str(exc), **kw)

class PipelineBatchOpts(DataModel):
    clean: bool = False
    clean_only: bool = False
    stat_only: bool = False
    fail: bool = False
    incremental: bool = False
    concurrent: bool = False
    max_workers: int = settings.ETL_DEFAULT_WORKERS
    max_threads: int = settings.ETL_DEFAULT_THREADS

    @model_validator(mode='after')
    def check_flags(self) -> Self:
        if self.clean_only and (self.clean or self.incremental or self.stat_only):
            raise ValueError(f'Cannot specify clean_only with clean, incremental, or stat_only')
        if self.stat_only and (self.clean or self.incremental or self.clean_only):
            raise ValueError(f'Cannot specify stat_only with clean, incremental, or clean_only')
        return self

class ScraperOpts(DataModel):
    selenium_max_procs: int = settings.SELENIUM_MAX_PROCS

class PipelineOpts(ScraperOpts):
    lazy: bool = True

class PipelineLog(DataModel):
    id: UUID = Field(alias='_id')
    stages: list[Stage] = Field(default_factory=list)
    states: list[StateCode] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    batch_opts: PipelineBatchOpts = Field(default_factory=PipelineBatchOpts)
    pipeline_opts: PipelineOpts = Field(default_factory=PipelineOpts)
    start: datetime|None = None
    end: datetime|None = None
    elapsed: float = 0
    errors: list[PipelineRunError] = Field(default_factory=list)
    runs: list[PipelineRunDetail] = Field(default_factory=list)
    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    def sync(self) -> None:
        if self.start:
            until = self.end or utils.utcnow()
            self.elapsed = (until - self.start).total_seconds()

    def get_load_changes(self) -> list[dict[str, Any]]:
        body = []
        for run in self.runs:
            if run.stage is not run.stage.Load:
                continue
            if not run.result or run.result['nochange']:
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
        for run in self.runs:
            if run.stage is not run.stage.Scrape:
                continue
            if run.end:
                elapsed = run.elapsed
            else:
                elapsed = None
            body.append(dict(
                state=run.state,
                elapsed=elapsed))
        body.sort(key=lambda x: x['elapsed'] or 0, reverse=True)
        return body

    def get_runs(self) -> list[dict[str, Any]]:
        body = []
        for run in self.runs:
            body.append(dict(
                stage=run.stage[0].upper(),
                state=run.state,
                elapsed=run.elapsed,
                failed=run.failed,
                nochange=run.result and run.result.get('nochange')))
        return body

    def get_short(self) -> dict[str, Any]:
        mapping = dict(
            id=str(self.id),
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
