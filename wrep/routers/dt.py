from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from .. import search, utils
from ..models import *

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
    state: StateCode|None = None,
    reported_before: datetime|None = None,
    reported_after: datetime|None = None,
    employees_min: int|None = None,
    draw: int = 1,
    limit: Limit = 25,
    offset: Offset = 0,
    order: str|None = None,
) -> ReportSearchResult:
    qp = dict(req.query_params)
    logger.info(f'{qp=}')
    employees_gt = None if employees_min is None else employees_min - 1
    params = dict(
        text=text,
        state=state,
        reported_before=reported_before,
        reported_after=reported_after,
        employees_gt=employees_gt,
        order=order)
    data, total = await search.search_with_total(ReportData, params, limit, offset)
    collstats = (await search.search_stats('reports'))['reports']
    return ReportSearchResult(
        data=data,
        recordsTotal=collstats['count'],
        recordsFiltered=total,
        draw=draw)
