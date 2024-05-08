from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from .. import utils
from ..models import *
from ..search import search

logger = utils.get_logger('api')
router = APIRouter()

@router.get('/reports', response_model_by_alias=False)
async def reports_list(
    text: str|None = None,
    company: str|None = None,
    state: State|None = None,
    location: str|None = None,
    naics: int|None = None,
    reported_after: datetime|None = None,
    reported_before: datetime|None = None,
    order: str|None = None,
    limit: Limit = 50,
    page: PageNumber = 1
) -> list[ReportData]:
    params = dict(
        text=text,
        company=company,
        state=state,
        location=location,
        naics=naics,
        reported_after=reported_after,
        reported_before=reported_before,
        order=order)
    return await search(ReportData, params, limit, (page - 1) * limit)

@router.get('/reports/{id}', response_model_by_alias=False)
async def report_get(id: UUID) -> ReportData:
    results = await search(ReportData, dict(id=id), 1)
    if results:
        return results[0]
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
