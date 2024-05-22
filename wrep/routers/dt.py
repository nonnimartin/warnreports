from __future__ import annotations

from fastapi import APIRouter, Request

from .. import search, utils
from ..models import *
from .api import CompanyParam, EmployeesParams, IdsParam, ReportedParams

logger = utils.get_logger('dt')
router = APIRouter()

class SearchResult(DataModel):
    recordsTotal: int
    recordsFiltered: int
    draw: int

class ReportSearchResult(SearchResult):
    data: list[ReportData]

@router.get('/reports', include_in_schema=False, response_model_by_alias=False)
async def search_reports(
    req: Request,
    text: str|None = None,
    id_not: IdsParam = None,
    state: str|None = None,
    reported: ReportedParams = ...,
    employees: EmployeesParams = ...,
    company: CompanyParam = None,
    company_id: IdsParam = None,
    draw: int = 1,
    limit: Limit = 25,
    offset: Offset = 0,
    order: str|None = None,
) -> ReportSearchResult:
    qp = dict(req.query_params)
    logger.info(f'{qp=}')
    params = dict(
        text=text,
        id_not=id_not,
        company=company,
        company_id=company_id,
        state=state.split(',') if state else None,
        **reported,
        **employees,
        order=order)
    data, total = await search.search_with_total(ReportData, params, limit, offset)
    collstats = (await search.search_stats('reports'))['reports']
    return ReportSearchResult(
        data=data,
        recordsTotal=collstats['count'],
        recordsFiltered=total,
        draw=draw)
