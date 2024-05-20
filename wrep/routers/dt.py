from __future__ import annotations

from fastapi import APIRouter, Request

from .. import utils, search
from ..models import *

logger = utils.get_logger('dt')
router = APIRouter()

class ReportDtResult(DataModel):
    data: list[ReportData]
    recordsTotal: int
    recordsFiltered: int
    draw: int

@router.get('/reports', include_in_schema=False, response_model_by_alias=False)
async def search_dt(
    req: Request,
    length: Limit,
    start: Offset,
    draw: int,
) -> ReportDtResult:
    qp = dict(req.query_params)
    order = parse_dt_order(qp)
    params = dict(order=order)
    text = qp.get('search[value]')
    if text:
        params.update(text=text)
    data, total = await search.search_with_total(ReportData, params, length, start)
    collstats = (await search.search_stats('reports'))['reports']
    return ReportDtResult(
        data=data,
        recordsTotal=collstats['count'],
        recordsFiltered=total,
        draw=draw)

def parse_dt_order(params: dict[str, str]) -> str|None:
    res = []
    for i in range(len(params)):
        try:
            field = params[f'order[{i}][name]']
        except KeyError:
            break
        if params[f'order[{i}][dir]'] == 'desc':
            field = f'-{field}'
        res.append(field)
    return ','.join(res) if res else None

