from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import Field
from starlette.datastructures import URL

from .. import settings, utils
from ..models import *
from ..search import *
from .common import *

logger = utils.get_logger('api')
router = APIRouter()

def search_opts(
    order: Annotated[
        str,
        Query(description='Order field name(s), comma-separated')] = None,
    limit: Limit = 50,
    offset: Offset = 0
):
    return dict(
        order=order,
        limit=limit,
        offset=offset)

SearchOpts = Annotated[dict, Depends(search_opts)]

class ReportDataView(ReportData):
    id: UUID = Field(
        title='ID',
        description='The unique report ID')
    artifacts: list[ArtifactDataView] = Field(
        default_factory=list,
        description='Downloadable artifacts (pdf, xlsx) archived from the source')

class CompanyDetailView(CompanyDetail):
    id: UUID = Field(
        title='ID',
        description='The internal company ID, for cross-referencing related reports')

class ArtifactDataView(ArtifactData):
    id: UUID = Field(title='ID')

class ArtifactDetailView(ArtifactDataView, ArtifactDetail):
    pass

def repopts(model: type) -> dict:
    return dict(response_model_by_alias=False, response_model=model)

@router.get('/reports', **repopts(list[ReportDataView]))
async def reports_list(req: Request, rep: Response, params: ReportSearchParams, opts: SearchOpts) -> list[ReportData]:
    return await search_response(req, rep, ReportData, params, opts)

@router.head('/reports', include_in_schema=False)
async def reports_list_head(req: Request, rep: Response, params: ReportSearchParams, opts: SearchOpts) -> Response:
    return await search_response(req, rep, ReportData, params, opts)

@router.head('/reports/{id}', include_in_schema=False)
@router.get('/reports/{id}', **repopts(ReportDataView))
async def report_get(id: UUID) -> ReportData:
    return await retrieve404(ReportData, id=[id])

@router.get('/companies', **repopts(list[CompanyDetailView]))
async def companies_list(req: Request, rep: Response, params: CompanySearchParams, opts: SearchOpts) -> list[CompanyDetail]:
    return await search_response(req, rep, CompanyDetail, params, opts)

@router.head('/companies', include_in_schema=False)
async def companies_list_head(req: Request, rep: Response, params: ReportSearchParams, opts: SearchOpts) -> Response:
    return await search_response(req, rep, CompanyDetail, params, opts)

@router.head('/companies/{id}', include_in_schema=False)
@router.get('/companies/{id}', **repopts(CompanyDetailView))
async def company_get(id: UUID) -> CompanyDetail:
    return await retrieve404(CompanyDetail, id=[id])

@router.get('/naics')
async def naics_list(req: Request, rep: Response, params: NaicsSearchParams, opts: SearchOpts) -> list[NaicsDetail]:
    return await search_response(req, rep, NaicsDetail, params, opts)

@router.head('/naics', include_in_schema=False)
async def naics_list_head(req: Request, rep: Response, params: NaicsSearchParams, opts: SearchOpts) -> Response:
    return await search_response(req, rep, NaicsDetail, params, opts)

@router.head('/naics/{id}', include_in_schema=False)
@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsDetail:
    return await retrieve404(NaicsDetail, id=[id])

@router.get('/states')
async def states_list(req: Request, rep: Response, params: StateSearchParams, opts: SearchOpts) -> list[StateDetail]:
    return await search_response(req, rep, StateDetail, params, opts)

@router.head('/states', include_in_schema=False)
async def states_list_head(req: Request, rep: Response, params: StateSearchParams, opts: SearchOpts) -> Response:
    return await search_response(req, rep, StateDetail, params, opts)

@router.head('/states/{id}', include_in_schema=False)
@router.get('/states/{id}')
async def state_get(id: StateCode) -> StateDetail:
    return await retrieve404(StateDetail, id=[id])

async def search_response[DM: DataModel](req: Request, rep: Response, model: type[DM], params: dict, opts: SearchOpts) -> list[DM]|Response:
    params = dict(params)
    opts = dict(opts)
    params['order'] = opts.pop('order')
    limit = opts['limit']
    if req.method == 'HEAD':
        opts['limit'] = 0
        rep.status_code = status.HTTP_204_NO_CONTENT
    res, total = await search_result(model, params, **opts)
    rep.headers['count'] = str(total)
    if (nexturl := get_next_url(req.url, total, opts['offset'], limit)):
        rep.headers['next'] = str(nexturl)
    if req.method == 'HEAD':
        return rep
    return res

def get_next_url(url: URL, total: int, offset: int, limit: int) -> URL|None:
    if not has_next_url(total, offset, limit):
        return
    baseurl = settings.SITE_URL
    params = dict(offset=offset + limit, limit=limit)
    return (url
        .remove_query_params(params)
        .include_query_params(**params)
        .replace(
            scheme=baseurl.scheme,
            hostname=baseurl.hostname,
            port=baseurl.port,
            path=baseurl.path.rstrip('/') + url.path))

def has_next_url(total: int, offset: int, limit: int) -> bool:
    return limit > 0 and total > offset + limit
