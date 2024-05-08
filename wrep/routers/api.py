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
    state: State|None = None,
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
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[NaicsData]:
    params = dict(
        code=code,
        prefix=prefix,
        title=title,
        text=text,
        order=order)
    return await search(NaicsData, params, limit, (page - 1) * limit)

@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsData:
    try:
        return await retrieve(NaicsData, id=id)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

@router.get('/companies')
async def companies_list(
    text: str|None = None,
    company: str|None = None,
    state: State|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[CompanyData]:
    params = dict(
        text=text,
        company=company,
        state=state,
        order=order)
    return await search(CompanyData, params, limit, (page - 1) * limit)

@router.get('/states')
async def states_list() -> list[StateData]:
    return await search(StateData)
