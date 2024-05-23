from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query

from ..models import *

__all__ = [
    'CompanySearchParams',
    'NaicsSearchParams',
    'ReportSearchParams',
    'StateSearchParams',
]

async def reported_params(
    reported_min: Annotated[
        datetime|None,
        Query(description='The minimum reported date (YYYY-MM-DD).')
    ] = None,
    reported_max: Annotated[
        datetime|None,
        Query(description='The maximum reported date (YYYY-MM-DD).')
    ] = None,
):
    return dict(
        reported_min=reported_min,
        reported_max=reported_max)

async def last_reported_params(
    last_reported_min: Annotated[
        datetime|None,
        Query(description='The minimum last_reported date (YYYY-MM-DD).')
    ] = None,
    last_reported_max: Annotated[
        datetime|None,
        Query(description='The maximum last_reported date (YYYY-MM-DD).')
    ] = None,
):
    return dict(
        last_reported_min=last_reported_min,
        last_reported_max=last_reported_max)

async def starting_params(
    starting_min: Annotated[
        datetime|None,
        Query(description='The minimum starting date (YYYY-MM-DD).')
    ] = None,
    starting_max: Annotated[
        datetime|None,
        Query(description='The maximum starting date (YYYY-MM-DD).')
    ] = None,
):
    return dict(
        starting_min=starting_min,
        starting_max=starting_max)

async def employees_params(employees_min: int|None = None, employees_max: int|None = None):
    return dict(
        employees_min=employees_min,
        employees_max=employees_max)

async def employees_sum_params(employees_sum_min: int|None = None, employees_sum_max: int|None = None):
    return dict(
        employees_sum_min=employees_sum_min,
        employees_sum_max=employees_sum_max)

async def reports_count_params(reports_count_min: int|None = None, reports_count_max: int|None = None):
    return dict(
        reports_count_min=reports_count_min,
        reports_count_max=reports_count_max)

async def companies_count_params(companies_count_min: int|None = None, companies_count_max: int|None = None):
    return dict(
        companies_count_min=companies_count_min,
        companies_count_max=companies_count_max)

async def report_search_params(
    text: str|None = None,
    state: StateParam = None,
    reported: ReportedParams = ...,
    starting: StartingParams = ...,
    employees: EmployeesParams = ...,
    company: CompanyParam = None,
    id_not: IdsParam = None,
    company_id: IdsParam = None,
    location: str|None = None,
    action: str|None = None,
    naics: NaicsParam = None,
):
    return dict(
        text=text,
        id_not=id_not,
        company=company,
        company_id=company_id,
        state=state,
        action=action,
        location=location,
        naics=naics,
        **reported,
        **starting,
        **employees)

async def company_search_params(
    id: IdsParam = None,
    text: str|None = None,
    name: CompanyParam= None,
    state: StateParam = None,
    naics: NaicsParam = None,
    employees_sum: EmployeesSumParams = ...,
    reports_count: ReportsCountParams = ...,
    last_reported: LastReportedParams = ...,
):
    return dict(
        id=id,
        text=text,
        name=name,
        state=state,
        naics=naics,
        **reports_count,
        **last_reported,
        **employees_sum)

async def naics_search_params(
    code: int|None = None,
    prefix: NaicsParam = None,
    title: str|None = None,
    reports_count: ReportsCountParams = ...,
    employees_sum: EmployeesSumParams = ...,
    companies_count: CompaniesCountParams = ...,
):
    return dict(
        code=code,
        prefix=prefix,
        title=title,
        **reports_count,
        **employees_sum,
        **companies_count)

async def state_search_params(
    reports_count: ReportsCountParams,
    last_reported: LastReportedParams,
):
    return reports_count | last_reported

CompanyParam = Annotated[list[CompanyName]|None, Query()]
StateParam = Annotated[list[StateCode]|None, Query()]
IdsParam = Annotated[list[UUID]|None, Query()]
NaicsParam = Annotated[list[int]|None, Query()]
ReportedParams = Annotated[dict, Depends(reported_params)]
StartingParams = Annotated[dict, Depends(starting_params)]
EmployeesParams = Annotated[dict, Depends(employees_params)]
EmployeesSumParams = Annotated[dict, Depends(employees_sum_params)]
ReportsCountParams = Annotated[dict, Depends(reports_count_params)]
LastReportedParams = Annotated[dict, Depends(last_reported_params)]
CompaniesCountParams = Annotated[dict, Depends(companies_count_params)]
ReportSearchParams = Annotated[dict, Depends(report_search_params)]
CompanySearchParams = Annotated[dict, Depends(company_search_params)]
NaicsSearchParams = Annotated[dict, Depends(naics_search_params)]
StateSearchParams = Annotated[dict, Depends(state_search_params)]
