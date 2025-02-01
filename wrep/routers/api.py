from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from .. import utils
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

def repopts(model: type):
    return dict(response_model_by_alias=False, response_model=model)

@router.get('/reports', **repopts(list[ReportDataView]))
async def reports_list(params: ReportSearchParams, opts: SearchOpts) -> list[ReportData]:
    params |= dict(order=opts.pop('order'))
    return await search(ReportData, params, **opts)

@router.get('/reports/{id}', **repopts(ReportDataView))
async def report_get(id: UUID) -> ReportData:
    return await retrieve404(ReportData, id=id)

@router.get('/companies', **repopts(list[CompanyDetailView]))
async def companies_list(params: CompanySearchParams, opts: SearchOpts) -> list[CompanyDetail]:
    params |= dict(order=opts.pop('order'))
    return await search(CompanyDetail, params, **opts)

@router.get('/companies/{id}', **repopts(CompanyDetailView))
async def company_get(id: UUID) -> CompanyDetail:
    return await retrieve404(CompanyDetail, id=[id])

@router.get('/naics')
async def naics_list(params: NaicsSearchParams, opts: SearchOpts) -> list[NaicsDetail]:
    params |= dict(order=opts.pop('order'))
    return await search(NaicsDetail, params, **opts)

@router.get('/naics/{id}')
async def naics_get(id: int) -> NaicsDetail:
    return await retrieve404(NaicsDetail, id=[id])

@router.get('/states')
async def states_list(params: StateSearchParams, opts: SearchOpts) -> list[StateDetail]:
    params |= dict(order=opts.pop('order'))
    return await search(StateDetail, params, **opts)

@router.get('/states/{id}')
async def state_get(id: StateCode) -> StateDetail:
    return await retrieve404(StateDetail, id=id)
