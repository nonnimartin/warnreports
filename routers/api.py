from __future__ import annotations

from fastapi import APIRouter

from models import *

router = APIRouter()

@router.get('/reports')
async def reports_list(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    location: str|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[ReportData]:
    fields = ReportData.orm_fields(Report)
    filters = ReportData.orm_filters(search, company, state, location)
    q = Report.select(*fields)
    q = q.where(*filters)
    q = q.order_by(
        Report.reported.desc(),
        Report.state.collate('NOCASE'),
        Report.company.collate('NOCASE'))
    q = q.limit(limit).offset(offset)
    return q

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
