from __future__ import annotations

from fastapi import APIRouter, Request

from .. import search, utils
from ..models import *
from .common import *

logger = utils.get_logger('dt')
router = APIRouter()

class SearchResult(DataModel):
    recordsTotal: int
    recordsFiltered: int
    draw: int

class ReportSearchResult(SearchResult):
    data: list[ReportData]

@router.get('/reports', response_model_by_alias=False)
async def search_reports(
    req: Request,
    params: ReportSearchParams,
    draw: int = 1,
    limit: Limit = 25,
    offset: Offset = 0,
    order: str|None = None,
) -> ReportSearchResult:
    qp = dict(req.query_params)
    logger.info(f'{qp=}')
    params = dict(params, order=order)
    data, total = await search.search_result(ReportData, params, limit, offset)
    collstats = (await search.search_stats('reports'))['reports']
    return ReportSearchResult(
        data=data,
        recordsTotal=collstats['count'],
        recordsFiltered=total,
        draw=draw)
