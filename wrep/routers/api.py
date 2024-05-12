from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from .. import utils
from ..models import *
from ..search import *

logger = utils.get_logger('api')
router = APIRouter()

@router.get('/reports', response_model_by_alias=False)
async def reports_list(
    text: str|None = None,
    company: str|None = None,
    state: StateCode|None = None,
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
    params = dict(
        text=text,
        company=company,
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
    try:
        return await retrieve(ReportData, id=id)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

@router.get('/naics')
async def naics_list(
    code: int|None = None,
    prefix: int|None = None,
    title: str|None = None,
    text: str|None = None,
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[NaicsDetail]:
    params = dict(
        code=code,
        prefix=prefix,
        title=title,
        text=text,
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        order=order)
    return await search(NaicsDetail, params, limit, (page - 1) * limit)

@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsDetail:
    try:
        return await retrieve(NaicsDetail, id=id)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

@router.get('/companies')
async def companies_list(
    text: str|None = None,
    company: str|None = None,
    state: StateCode|None = None,
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    last_reported_after: datetime|None = None,
    last_reported_before: datetime|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[CompanyDetail]:
    params = dict(
        text=text,
        company=company,
        state=state,
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        last_reported_after=last_reported_after,
        last_reported_before=last_reported_before,
        order=order)
    return await search(CompanyDetail, params, limit, (page - 1) * limit)

@router.get('/states')
async def states_list(
    state: StateCode|None = None,
    reports_count_gt: int|None = None,
    reports_count_lt: int|None = None,
    last_reported_after: datetime|None = None,
    last_reported_before: datetime|None = None,
    order: str|None = None
) -> list[StateDetail]:
    params = dict(
        state=state,
        reports_count_gt=reports_count_gt,
        reports_count_lt=reports_count_lt,
        last_reported_after=last_reported_after,
        last_reported_before=last_reported_before,
        order=order)
    return await search(StateDetail, params)

@router.get('/states/{state}')
async def state_get(state: StateCode) -> StateDetail:
    try:
        return await retrieve(StateDetail, state=state)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
