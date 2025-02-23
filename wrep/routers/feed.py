from __future__ import annotations

import base64
import binascii
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from feedgen.feed import FeedGenerator
from pydantic import ValidationError
from starlette.datastructures import URL

from .. import settings, utils
from ..backends.mongo import Search, filters
from ..models import *
from .common import (FeedSearchParams, clean_feed_params, feed_id_encode,
                     site_absurl)

logger = utils.get_logger('feed')
router = APIRouter()

@router.get('/rss')
async def rss_default() -> HTMLResponse:
    return await feed_query('rss', {})

@router.get('/atom')
async def atom_default() -> HTMLResponse:
    return await feed_query('atom', {})

@router.head('/rss')
@router.head('/atom')
async def default_head(rep: Response) -> Response:
    rep.status_code = status.HTTP_204_NO_CONTENT
    return rep

@router.get('/rss/{id}')
async def rss_permalink(rep: Response, id: str) -> HTMLResponse:
    feed_id_header(rep, id)
    return await feed_permalink('rss', id)

@router.get('/atom/{id}')
async def atom_permalink(rep: Response, id: str) -> HTMLResponse:
    feed_id_header(rep, id)
    return await feed_permalink('atom', id)

@router.head('/rss/{id}')
@router.head('/atom/{id}')
async def permalink_head(rep: Response, id: str) -> Response:
    feed_id_header(rep, id)
    rep.status_code = status.HTTP_204_NO_CONTENT
    return rep

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
    params = clean_feed_params(params)
    title = f'warnreports {query_description(params)}'.strip()
    id = feed_id_encode(params)
    url = str(id_permalink(id, fmt))
    feed = FeedGenerator()
    feed.id(url)
    feed.link(href=url, rel='self')
    feed.language('en')
    feed.title(title)
    feed.description(title)
    feed.generator('')
    params = dict(params, order='-reported')
    filter = filters[ReportData].model_validate(params)
    result = Search(filter, settings.FEED_ENTRY_LIMIT)
    async for report in result.objs():
        entry = feed.add_entry(order='append')
        entry.id((str(report.id)))
        entry.title(report.company)
        entry.link(href=str(report_link(report)))
        entry.published(report.tzreplace(report.reported))
        entry.updated(entry.published())
        entry.description(entry_description(report))
    return getattr(feed, f'{fmt}_str')(pretty=True)

def entry_description(report: ReportData) -> str:
    descs = [report.state]
    if report.employees:
        descs.append(f'{report.employees} employees')
    if report.starting:
        descs.append(f'on {report.starting.date()}')
    if report.action:
        descs.append(report.action)
    if report.location:
        descs.append(report.location)
    return ' | '.join(descs)

def query_description(params: FeedSearchParams) -> str:
    params = clean_feed_params(params)
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

def id_decode(id: str) -> dict[str, Any]:
    try:
        q = base64.urlsafe_b64decode(id).decode()
    except (binascii.Error, UnicodeDecodeError):
        q = base64.b32hexdecode(id, casefold=True).decode()
    params = parse_qs(q)
    for key in ('employees_min', 'naics'):
        if key in params:
            params[key] = list(map(int, params[key]))
    params = {
        k: v if k in ('naics', 'state') else v[0]
        for k, v in params.items()}
    return clean_feed_params(params)

def id_permalink(id: str, fmt: str) -> URL:
    path = f'/feed/{fmt}'
    if id:
        path = f'{path}/{id}'
    return site_absurl(path)

def feed_id_header(rep: Response, id: str) -> Response:
    try:
        id = feed_id_encode(id_decode(id))
    except ValidationError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if id:
        rep.headers['feed-id'] = id
    return rep

def report_link(report: ReportData) -> URL:
    return site_absurl(f'/r/{report.id}')
