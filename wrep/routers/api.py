from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from .. import utils
from ..models import *
from ..search import *

logger = utils.get_logger('api')
router = APIRouter()

@router.get('/reports', response_model_by_alias=False)
async def reports_list(
    text: str|None = None,
    id_not: Annotated[list[UUID]|None, Query()] = None,
    company: Annotated[list[CompanyName]|None, Query()] = None,
    company_id: Annotated[list[UUID]|None, Query()] = None,
    state: Annotated[list[StateCode]|None, Query()] = None,
    location: str|None = None,
    action: str|None = None,
    naics: int|None = None,
    reported_after: datetime|None = None,
    reported_before: datetime|None = None,
    starting_after: datetime|None = None,
    starting_before: datetime|None = None,
    employees_gt: int|None = None,
    employees_lt: int|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[ReportData]:
    logger.info(f'{company=}')
    params = dict(
        text=text,
        id_not=id_not,
        company=company,
        company_id=company_id,
        state=state,
        action=action,
        location=location,
        naics=naics,
        reported_after=reported_after,
        reported_before=reported_before,
        starting_after=starting_after,
        starting_before=starting_before,
        employees_gt=employees_gt,
        employees_lt=employees_lt,
        order=order)
    return await search(ReportData, params, limit, (page - 1) * limit)

@router.get('/reports/{id}', response_model_by_alias=False)
async def report_get(id: UUID) -> ReportData:
    return await retrieve404(ReportData, id=id)

@router.get('/states')
async def states_list(
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    last_reported_after: datetime|None = None,
    last_reported_before: datetime|None = None,
    order: str|None = None
) -> list[StateDetail]:
    params = dict(
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        last_reported_after=last_reported_after,
        last_reported_before=last_reported_before,
        order=order)
    return await search(StateDetail, params)

@router.get('/states/{id}')
async def state_get(id: StateCode) -> StateDetail:
    return await retrieve404(StateDetail, id=id)

@router.get('/companies', response_model_by_alias=False)
async def companies_list(
    id: Annotated[list[UUID]|None, Query()] = None,
    text: str|None = None,
    name: Annotated[list[CompanyName]|None, Query()] = None,
    state: Annotated[list[StateCode]|None, Query()] = None,
    naics: int|None = None,
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    employees_sum_gt: int|None = None,
    employees_sum_lt: int|None = None,
    last_reported_after: datetime|None = None,
    last_reported_before: datetime|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[CompanyDetail]:
    params = dict(
        id=id,
        text=text,
        name=name,
        state=state,
        naics=naics,
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        employees_sum_gt=employees_sum_gt,
        employees_sum_lt=employees_sum_lt,
        last_reported_after=last_reported_after,
        last_reported_before=last_reported_before,
        order=order)
    return await search(CompanyDetail, params, limit, (page - 1) * limit)

@router.get('/companies/{id}', response_model_by_alias=False)
async def company_get(id: UUID) -> CompanyDetail:
    return await retrieve404(CompanyDetail, id=[id])

@router.get('/naics')
async def naics_list(
    code: int|None = None,
    prefix: int|None = None,
    title: str|None = None,
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    companies_count_gt: int|None = None,
    companies_count_lt: int|None = None,
    employees_sum_gt: int|None = None,
    employees_sum_lt: int|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[NaicsDetail]:
    params = dict(
        code=code,
        prefix=prefix,
        title=title,
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        companies_count_gt=companies_count_gt,
        companies_count_lt=companies_count_lt,
        employees_sum_gt=employees_sum_gt,
        employees_sum_lt=employees_sum_lt,
        order=order)
    return await search(NaicsDetail, params, limit, (page - 1) * limit)

@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsDetail:
    return await retrieve404(NaicsDetail, id=id)
