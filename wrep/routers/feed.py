from __future__ import annotations

import base64
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from feedgen.feed import FeedGenerator
from pydantic import ValidationError

from .. import settings, utils
from ..models import *
from ..search import *
from .common import NaicsParam, StateParam, TextSearchParam

logger = utils.get_logger('feed')
router = APIRouter()
templates = Jinja2Templates(env=utils.jinja_env())

def search_params(
    text: TextSearchParam = None,
    state: StateParam = None,
    naics: NaicsParam = None,
    employees_min: int = None,
):
    return dict(
        text=text,
        state=state,
        naics=naics,
        employees_min=employees_min)

FeedSearchParams = Annotated[dict, Depends(search_params)]

@router.get('/')
async def feed_index(req: Request, params: FeedSearchParams) -> HTMLResponse:
    id = id_encode(params)
    is_custom = any(params.values())
    custom_desc = query_description(params)
    permalinks = {fmt: id_permalink(id, fmt) for fmt in ('rss', 'atom')}
    context = dict(
        params=params,
        is_custom=is_custom,
        custom_desc=custom_desc,
        permalinks=permalinks)
    params = dict(params, order='-reported')
    reports = await search(ReportData, params, 50)
    states = await search(StateDetail)
    context.update(reports=reports, states=states)
    return templates.TemplateResponse(req, 'feed.jinja', context)

@router.get('/rss')
async def rss_query(params: FeedSearchParams) -> HTMLResponse:
    return await feed_query('rss', params)

@router.get('/rss/{id}')
async def rss_permalink(id: str) -> HTMLResponse:
    return await feed_permalink('rss', id)

@router.get('/atom')
async def atom_query(params: FeedSearchParams) -> HTMLResponse:
    return await feed_query('atom', params)

@router.get('/atom/{id}')
async def atom_permalink(id: str) -> HTMLResponse:
    return await feed_permalink('atom', id)

from ..main import app


async def feed_query(fmt: str, params: FeedSearchParams) -> HTMLResponse:
    return HTMLResponse(content=await build_feed(fmt, params), media_type='text/xml')

async def feed_permalink(fmt: str, id: str) -> HTMLResponse:
    try:
        params = id_decode(id)
    except ValidationError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return await feed_query(fmt, params)

async def build_feed(fmt: str, params: FeedSearchParams) -> bytes:
    title = f'WARN Reports {query_description(params)}'.strip()
    id = id_encode(params)
    url = id_permalink(id, fmt)
    feed = FeedGenerator()
    feed.id(url)
    feed.link(href=url, rel='self')
    feed.language('en')
    feed.title(title)
    feed.description(title)
    params = dict(params, order='-reported')
    template = utils.get_template('reports/feed.jinja')
    for report in await search(ReportData, params, settings.FEED_ENTRY_LIMIT):
        entry = feed.add_entry(order='append')
        entry.id((str(report.id)))
        entry.title(report.company)
        entry.link(href=report_link(report))
        entry.published(report.tzreplace(report.reported))
        entry.updated(entry.published())
        entry.description(template.render(report=report))
    return getattr(feed, f'{fmt}_str')(pretty=True)

def query_description(params: FeedSearchParams) -> str:
    params = {k: v for k, v in params.items() if v is not None}
    descs = []
    if (state := params.pop('state', None)) is not None:
        descs.append(','.join(state))
    if (employees_min := params.pop('employees_min', None)) is not None:
        descs.append(f'{employees_min}+')
    if (naics := params.pop('naics', None)) is not None:
        descs.append(f'NAICS={','.join(map(str, naics))}')
    if (text := params.pop('text', None)):
        descs.append(str(text))
    descs.extend(filter(None, urlencode(params).split('&')))
    return ' '.join(descs)

def id_encode(params: FeedSearchParams) -> str:
    items = []
    for k in sorted(params):
        if (v := params[k]) is not None:
            if not isinstance(v, list):
                v = [v]
            for value in v:
                items.append((k, value))
    q = urlencode(items)
    return base64.b32hexencode(q.encode()).decode().lower()

def id_decode(id: str) -> dict[str, Any]:
    q = base64.b32hexdecode(id, casefold=True).decode()
    params = parse_qs(q)
    for key in ('employees_min', 'naics'):
        if key in params:
            params[key] = list(map(int, params[key]))
    return {
        k: v if k in ('naics', 'state') else v[0]
        for k, v in params.items()}

def id_permalink(id: str, fmt: str) -> str:
    if id:
        href = app.url_path_for(f'{fmt}_permalink', id=id)
    else:
        href = app.url_path_for(f'{fmt}_query')
    return settings.SITE_URL + href

def report_link(report: ReportData) -> str:
    return settings.SITE_URL + app.url_path_for('report_view', id=report.id)
