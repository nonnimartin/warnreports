from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

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
    limit: Limit = 50,
    offset: Offset = 0
) -> list[ReportData]:
    params = dict(
        text=text,
        company=company,
        state=state,
        location=location,
        naics=naics,
        reported_after=reported_after,
        reported_before=reported_before)
    return await search(ReportData, params, limit, offset)

@router.get('/companies')
async def companies_list(
    text: str|None = None,
    company: str|None = None,
    state: State|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[CompanyData]:
    params = dict(text=text, company=company, state=state)
    return await search(CompanyData, params, limit, offset)

@router.get('/states')
async def states_list() -> list[StateData]:
    return await search(StateData)
