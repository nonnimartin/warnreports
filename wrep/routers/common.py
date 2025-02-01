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

TextSearchParam = Annotated[str, Query(description='General text search')]
CompanyParam = Annotated[list[CompanyName], Query(description='The company name')]
StateParam = Annotated[list[StateCode], Query(description='The 2-letter state postal code')]
IdsParam = Annotated[list[UUID], Query(description='The unique record ID(s)')]
NaicsParam = Annotated[list[int], Query(description='The 2 to 6 digit NAICS code')]
NaicsTitleParam = Annotated[str, Query(description='The NAICS industry title')]
NaicsRootParam = Annotated[list[int], Query(description='The 2 digit root NAICS code')]

def reported_params(
    reported_min: Annotated[
        datetime,
        Query(description='The minimum reported date (YYYY-MM-DD)')] = None,
    reported_max: Annotated[
        datetime,
        Query(description='The maximum reported date (YYYY-MM-DD)')] = None,
):
    return dict(
        reported_min=reported_min,
        reported_max=reported_max)

def last_reported_params(
    last_reported_min: Annotated[
        datetime,
        Query(description='The minimum last_reported date (YYYY-MM-DD)')] = None,
    last_reported_max: Annotated[
        datetime,
        Query(description='The maximum last_reported date (YYYY-MM-DD)')] = None,
):
    return dict(
        last_reported_min=last_reported_min,
        last_reported_max=last_reported_max)

def starting_params(
    starting_min: Annotated[
        datetime,
        Query(description='The minimum starting date (YYYY-MM-DD)')] = None,
    starting_max: Annotated[
        datetime,
        Query(description='The maximum starting date (YYYY-MM-DD)')] = None,
):
    return dict(
        starting_min=starting_min,
        starting_max=starting_max)

def employees_params(
    employees_min: Annotated[
        int,
        Query(description='The minimum employees affected')] = None,
    employees_max: Annotated[
        int,
        Query(description='The maximum employees affected')] = None,
):
    return dict(
        employees_min=employees_min,
        employees_max=employees_max)

def employees_sum_params(
    employees_sum_min: Annotated[
        int,
        Query(description='The minimum sum total employees affected')] = None,
    employees_sum_max: Annotated[
        int,
        Query(description='The maximum sum total employees affected')] = None,
):
    return dict(
        employees_sum_min=employees_sum_min,
        employees_sum_max=employees_sum_max)

def reports_count_params(
    reports_count_min: Annotated[
        int,
        Query(description='The minimum report count')] = None,
    reports_count_max: Annotated[
        int,
        Query(description='The maximum report count')] = None,
):
    return dict(
        reports_count_min=reports_count_min,
        reports_count_max=reports_count_max)

def companies_count_params(
    companies_count_min: Annotated[
        int,
        Query(description='The minimum companies count')] = None,
    companies_count_max: Annotated[
        int,
        Query(description='The maximum companies count')] = None,
):
    return dict(
        companies_count_min=companies_count_min,
        companies_count_max=companies_count_max)

def states_count_params(
    states_count_min: Annotated[
        int,
        Query(description='The minimum states count')] = None,
    states_count_max: Annotated[
        int,
        Query(description='The maximum states count')] = None,
):
    return dict(
        states_count_min=states_count_min,
        states_count_max=states_count_max)

def report_search_params(
    text: TextSearchParam = None,
    state: StateParam = None,
    reported: ReportedParams = ...,
    starting: StartingParams = ...,
    employees: EmployeesParams = ...,
    company: CompanyParam = None,
    company_id: IdsParam = None,
    naics: NaicsParam = None,
    action: Annotated[str, Query(description='The action (layoff, closure, etc.)')] = None,
    location: Annotated[str, Query(description='Location details')] = None,
    id_not: Annotated[IdsParam, Query(include_in_schema=False)] = None,
):
    return dict(
        text=text,
        company=company,
        company_id=company_id,
        state=state,
        action=action,
        location=location,
        naics=naics,
        id_not=id_not,
        **reported,
        **starting,
        **employees)

def company_search_params(
    id: IdsParam = None,
    text: TextSearchParam = None,
    name: CompanyParam = None,
    state: StateParam = None,
    naics: NaicsParam = None,
    employees_sum: EmployeesSumParams = ...,
    reports_count: ReportsCountParams = ...,
    states_count: StatesCountParams = ...,
    last_reported: LastReportedParams = ...,
):
    return dict(
        id=id,
        text=text,
        name=name,
        state=state,
        naics=naics,
        **reports_count,
        **states_count,
        **last_reported,
        **employees_sum)

def naics_search_params(
    id: NaicsParam = None,
    prefix: NaicsParam = None,
    parent: Annotated[NaicsParam, Query(description='Restrict to direct children')] = None,
    includes: Annotated[NaicsParam, Query(description='Also include ancestors')] = None,
    root: NaicsRootParam = None,
    is_leaf: bool|None = None,
    title: NaicsTitleParam = None,
    state: StateParam = None,
    depth_min: Annotated[int, Query(description='The minimum tree depth')] = None,
    depth_max: Annotated[int, Query(description='The maximum tree depth')] = None,
    reports_count: ReportsCountParams = ...,
    employees_sum: EmployeesSumParams = ...,
    companies_count: CompaniesCountParams = ...,
    states_count: StatesCountParams = ...,
    last_reported: LastReportedParams = ...,
):
    return dict(
        id=id,
        prefix=prefix,
        parent=parent,
        includes=includes,
        title=title,
        root=root,
        is_leaf=is_leaf,
        state=state,
        depth_min=depth_min,
        depth_max=depth_max,
        **reports_count,
        **states_count,
        **last_reported,
        **employees_sum,
        **companies_count)

def state_search_params(
    reports_count: ReportsCountParams,
    last_reported: LastReportedParams,
):
    return reports_count | last_reported

ReportedParams = Annotated[dict, Depends(reported_params)]
StartingParams = Annotated[dict, Depends(starting_params)]
EmployeesParams = Annotated[dict, Depends(employees_params)]
EmployeesSumParams = Annotated[dict, Depends(employees_sum_params)]
ReportsCountParams = Annotated[dict, Depends(reports_count_params)]
StatesCountParams = Annotated[dict, Depends(states_count_params)]
LastReportedParams = Annotated[dict, Depends(last_reported_params)]
CompaniesCountParams = Annotated[dict, Depends(companies_count_params)]
ReportSearchParams = Annotated[dict, Depends(report_search_params)]
CompanySearchParams = Annotated[dict, Depends(company_search_params)]
NaicsSearchParams = Annotated[dict, Depends(naics_search_params)]
StateSearchParams = Annotated[dict, Depends(state_search_params)]
