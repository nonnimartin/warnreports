from __future__ import annotations

import base64
from typing import Annotated, Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from feedgen.feed import FeedGenerator

from .. import settings, utils
from ..models import *
from ..search import *
from .api import NaicsParam, StateParam

logger = utils.get_logger('feed')
router = APIRouter()
templates = Jinja2Templates(env=utils.jinja_env())

async def common_form(
    text: str|None = None,
    state: StateParam = None,
    naics: NaicsParam = None,
    employees_min: int|None = None,
):
    return dict(
        text=text,
        state=state,
        naics=naics,
        employees_min=employees_min)

FormDep = Annotated[dict, Depends(common_form)]

@router.get('/', include_in_schema=False)
async def feed_index(
    req: Request,
    form: FormDep,
    limit: Limit = 50,
    offset: Offset = 0
) -> HTMLResponse:
    id = id_encode(form)
    params = dict(form)
    params.update(order='-reported')
    permalinks = {fmt: id_permalink(id, fmt) for fmt in ('rss', 'atom')}
    reports = await search(ReportData, params, limit, offset)
    context = dict(reports=reports, permalinks=permalinks, form=form)
    is_custom = any(form.values())
    custom_desc = query_description(form)
    states = await search(StateDetail)
    context.update(is_custom=is_custom, custom_desc=custom_desc, states=states)
    return templates.TemplateResponse(req, 'feed.jinja', context)

def feed_query(fmt: str):
    async def query(form: FormDep) -> HTMLResponse:
        content = await build_feed(fmt, form)
        return HTMLResponse(content=content, media_type='text/xml')
    query.__name__ = fmt
    return query

def feed_permalink(fmt: str):
    async def permalink(id: str) -> HTMLResponse:
        try:
            params = id_decode(id)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        content = await build_feed(fmt, params)
        return HTMLResponse(content=content, media_type='text/xml')
    permalink.__name__ = f'{fmt}_permalink'
    return permalink

router.get('/rss')(feed_query('rss'))
router.get('/rss/{id}')(feed_permalink('rss'))
router.get('/atom')(feed_query('atom'))
router.get('/atom/{id}')(feed_permalink('atom'))

async def build_feed(fmt: str, form: FormDep) -> bytes:
    id = id_encode(form)
    title = f'WARN Reports {query_description(form)}'.strip()
    url = id_permalink(id, fmt)
    feed = FeedGenerator()
    feed.id(url)
    feed.link(href=url, rel='self')
    feed.language('en')
    feed.title(title)
    feed.description(title)
    params = dict(form)
    params.update(order='-reported')
    template = utils.get_template('reports/feed.jinja')
    for report in await search(ReportData, params, settings.FEED_ENTRY_LIMIT):
        entry = feed.add_entry(order='append')
        entry.id((str(report.id)))
        entry.title(report.company)
        entry.link(href=f'{settings.SITE_URL}/r/{report.id}')
        entry.published(report.tzreplace(report.reported))
        entry.updated(entry.published())
        entry.description(template.render(report=report))
    return getattr(feed, f'{fmt}_str')(pretty=True)

def query_description(form: FormDep) -> str:
    params = {k: v for k, v in form.items() if v is not None}
    descs = []
    if (state := params.pop('state', None)) is not None:
        descs.append(','.join(state))
    if (employees := params.pop('employees_min', None)) is not None:
        descs.append(f'{employees}+')
    if (naics := params.pop('naics', None)) is not None:
        descs.append(f'NAICS={','.join(map(str, naics))}')
    if (text := params.pop('text', None)):
        descs.append(text)
    descs.extend(filter(None, urlencode(params).split('&')))
    return ' '.join(descs)

def id_encode(form: FormDep) -> str:
    params = {k: form[k] for k in sorted(form) if form[k]}
    q = urlencode(params)
    return base64.b32hexencode(q.encode()).decode().lower()

def id_decode(id: str) -> dict[str, Any]:
    q = base64.b32hexdecode(id, casefold=True).decode()
    params = parse_qs(q)
    for key in ('employees_min', 'naics'):
        if key in params:
            params[key] = list(map(int, params[key]))
    return {k: v[0] for k, v in params.items()}

def id_permalink(id: str, fmt: str) -> str:
    return '/'.join((f'{settings.SITE_URL}/feed/{fmt}', id)).rstrip('/')
