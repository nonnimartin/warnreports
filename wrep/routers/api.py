from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Depends

from .. import utils
from ..models import *
from ..search import *

logger = utils.get_logger('api')
router = APIRouter()

async def common_params(order: str|None = None, limit: Limit = 50, page: PageNumber = 1):
    return dict(order=order, limit=limit, offset=(page - 1) * limit)

async def reported_params(reported_min: datetime|None = None, reported_max: datetime|None = None):
    return dict(reported_min=reported_min, reported_max=reported_max)

async def last_reported_params(last_reported_min: datetime|None = None, last_reported_max: datetime|None = None):
    return dict(last_reported_min=last_reported_min, last_reported_max=last_reported_max)

async def starting_params(starting_min: datetime|None = None, starting_max: datetime|None = None):
    return dict(starting_min=starting_min, starting_max=starting_max)

async def employees_params(employees_min: int|None = None, employees_max: int|None = None):
    return dict(employees_min=employees_min, employees_max=employees_max)

async def employees_sum_params(employees_sum_min: int|None = None, employees_sum_max: int|None = None):
    return dict(employees_sum_min=employees_sum_min, employees_sum_max=employees_sum_max)

async def reports_count_params(reports_count_min: int|None = None, reports_count_max: int|None = None):
    return dict(reports_count_min=reports_count_min, reports_count_max=reports_count_max)

async def companies_count_params(companies_count_min: int|None = None, companies_count_max: int|None = None):
    return dict(companies_count_min=companies_count_min, companies_count_max=companies_count_max)

CommonParams = Annotated[dict, Depends(common_params)]
CompanyParam = Annotated[list[CompanyName]|None, Query()]
StateParam = Annotated[list[StateCode]|None, Query()]
IdsParam = Annotated[list[UUID]|None, Query()]
NaicsParam = Annotated[list[int]|None, Query()]
ReportedParams = Annotated[dict, Depends(reported_params)]
StartingParams = Annotated[dict, Depends(starting_params)]
EmployeesParams = Annotated[dict, Depends(employees_params)]
EmployeesSumParams = Annotated[dict, Depends(employees_sum_params)]
ReportsCountParams = Annotated[dict, Depends(reports_count_params)]
LastReportedParams = Annotated[dict, Depends(last_reported_params)]
CompaniesCountParams = Annotated[dict, Depends(companies_count_params)]

@router.get('/reports', response_model_by_alias=False)
async def reports_list(
    text: str|None = None,
    state: StateParam = None,
    reported: ReportedParams = ...,
    starting: StartingParams = ...,
    employees: EmployeesParams = ...,
    company: CompanyParam = None,
    id_not: IdsParam = None,
    company_id: IdsParam = None,
    location: str|None = None,
    action: str|None = None,
    naics: NaicsParam = None,
    commons: CommonParams = ...,
) -> list[ReportData]:
    params = dict(
        text=text,
        id_not=id_not,
        company=company,
        company_id=company_id,
        state=state,
        action=action,
        location=location,
        naics=naics,
        **reported,
        **starting,
        **employees,
        order=commons['order'])
    return await search(ReportData, params, commons['limit'], commons['offset'])

@router.get('/reports/{id}', response_model_by_alias=False)
async def report_get(id: UUID) -> ReportData:
    return await retrieve404(ReportData, id=id)

@router.get('/states')
async def states_list(
    reports_count: ReportsCountParams,
    last_reported: LastReportedParams,
    order: str|None = None
) -> list[StateDetail]:
    params = dict(**reports_count, **last_reported, order=order)
    return await search(StateDetail, params)

@router.get('/states/{id}')
async def state_get(id: StateCode) -> StateDetail:
    return await retrieve404(StateDetail, id=id)

@router.get('/companies', response_model_by_alias=False)
async def companies_list(
    commons: CommonParams,
    id: IdsParam = None,
    text: str|None = None,
    name: CompanyParam= None,
    state: StateParam = None,
    naics: NaicsParam = None,
    employees_sum: EmployeesSumParams = ...,
    reports_count: ReportsCountParams = ...,
    last_reported: LastReportedParams = ...,
) -> list[CompanyDetail]:
    params = dict(
        id=id,
        text=text,
        name=name,
        state=state,
        naics=naics,
        **reports_count,
        **last_reported,
        **employees_sum,
        order=commons['order'])
    return await search(CompanyDetail, params, commons['limit'], commons['offset'])

@router.get('/companies/{id}', response_model_by_alias=False)
async def company_get(id: UUID) -> CompanyDetail:
    return await retrieve404(CompanyDetail, id=[id])

@router.get('/naics')
async def naics_list(
    commons: CommonParams,
    code: int|None = None,
    prefix: NaicsParam = None,
    title: str|None = None,
    reports_count: ReportsCountParams = ...,
    employees_sum: EmployeesSumParams = ...,
    companies_count: CompaniesCountParams = ...,
) -> list[NaicsDetail]:
    params = dict(
        code=code,
        prefix=prefix,
        title=title,
        **reports_count,
        **employees_sum,
        **companies_count,
        order=commons['order'])
    return await search(NaicsDetail, params, commons['limit'], commons['offset'])

@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsDetail:
    return await retrieve404(NaicsDetail, id=id)
