from __future__ import annotations

from fastapi import APIRouter

from .. import utils, settings
from ..models import *

logger = utils.get_logger('api')
router = APIRouter()

@router.get('/reports', response_model_by_alias=False)
async def reports_list(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    location: str|None = None,
    naics: int|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[ReportData]:
    args = (search, company, state, location, naics, limit, offset)
    if settings.MONGODB_ENABLED:
        return await search_mongo(*args)
    else:
        return await search_sql(*args)

@router.get('/companies')
async def companies_list(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[CompanyData]:
    fields = CompanyData.orm_fields(Report)
    filters = ReportData.orm_filters(search, company, state)
    q = Report.select(*fields).distinct()
    q = q.where(*filters)
    q = q.order_by(Report.company.collate('NOCASE'))
    q = q.limit(limit).offset(offset)
    return q

@router.get('/states')
async def states_list() -> list[StateData]:
    fields = StateData.orm_fields(Report)
    q = Report.select(*fields).distinct()
    q = q.order_by(Report.state)
    return q

async def search_mongo(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    location: str|None = None,
    naics: int|None = None,
    limit: Limit = 50,
    offset: Offset = 0
):
    args = (search, company, state, location, naics)
    filters = dict(ReportData.doc_filters(*args))
    cur = reports_coll.find(filters)
    cur = cur.sort([
        ('reported', -1),
        'state',
        'company'])
    cur = cur.skip(offset)
    return await cur.to_list(limit)

async def search_sql(
    search: str|None,
    company: str|None,
    state: State|None,
    location: str|None,
    naics: int|None,
    limit: Limit,
    offset: Offset
):
    args = (search, company, state, location, naics)
    filters = ReportData.orm_filters(*args)
    fields = ReportData.orm_fields(Report)
    q = Report.select(*fields)
    q = q.where(*filters)
    q = q.order_by(
        Report.reported.desc(),
        Report.state.collate('NOCASE'),
        Report.company.collate('NOCASE'))
    q = q.limit(limit).offset(offset)
    return q