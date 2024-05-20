from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, HTTPException, status, Request
from fastapi.responses import HTMLResponse
from feedgen.feed import FeedGenerator
from fastapi.templating import Jinja2Templates

from .. import settings, utils
from ..models import *
from ..search import *

logger = utils.get_logger('feed')
router = APIRouter()
templates = Jinja2Templates(env=utils.jinja_env())

def feed_query(fmt: str):
    async def query(
        text: str|None = None,
        company: str|None = None,
        state: StateCode|None = None,
        location: str|None = None,
        action: str|None = None,
        naics: int|None = None,
        employees: int|None = None,
    ) -> HTMLResponse:
        form = dict(
            text=text,
            company=company,
            state=state,
            action=action,
            location=location,
            naics=naics,
            employees=employees)
        content = await build_feed(fmt, **form)
        return HTMLResponse(content=content, media_type='text/xml')
    query.__name__ = fmt
    return query

def feed_permalink(fmt: str):
    async def permalink(id: str) -> HTMLResponse:
        try:
            params = id_decode(id)
        except ValueError:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        content = await build_feed(fmt, **params)
        return HTMLResponse(content=content, media_type='text/xml')
    permalink.__name__ = f'{fmt}_permalink'
    return permalink

router.get('/rss')(feed_query('rss'))
router.get('/rss/{id}')(feed_permalink('rss'))
router.get('/atom')(feed_query('atom'))
router.get('/atom/{id}')(feed_permalink('atom'))

async def build_feed(fmt: str, **kw) -> bytes:
    id = id_encode(**kw)
    title = f'WARN Reports {query_description(**kw)}'.strip()
    url = id_permalink(id, fmt)
    feed = FeedGenerator()
    feed.id(url)
    feed.link(href=url, rel='self')
    feed.language('en')
    feed.title(title)
    feed.description(title)
    params = dict(kw)
    employees = params.pop('employees', None)
    params.update(
        order='-reported',
        employees_gt=employees - 1 if employees else None)
    template = utils.get_template('reports/feed.jinja')
    for report in (await search(ReportData, params, settings.FEED_ENTRY_LIMIT))[0]:
        entry = feed.add_entry(order='append')
        entry.id((str(report.id)))
        entry.title(report.company)
        entry.link(href=f'{settings.SITE_URL}/r/{report.id}')
        entry.published(report.tzreplace(report.reported))
        entry.updated(entry.published())
        entry.description(template.render(report=report))
    return getattr(feed, f'{fmt}_str')(pretty=True)

@router.get('/', include_in_schema=False)
async def feed_index(
    req: Request,
    text: str|None = None,
    company: str|None = None,
    state: StateCode|None = None,
    location: str|None = None,
    action: str|None = None,
    naics: int|None = None,
    employees: int|None = None,
    limit: Limit = 50,
    offset: Offset = 0) -> HTMLResponse:
    form = dict(
        text=text,
        company=company,
        state=state,
        action=action,
        location=location,
        naics=naics,
        employees=employees)
    id = id_encode(**form)
    params = dict(form)
    params.pop('employees')
    params.update(
        order='-reported',
        employees_gt=employees - 1 if employees else None)
    permalinks = {fmt: id_permalink(id, fmt) for fmt in ('rss', 'atom')}
    reports = (await search(ReportData, params, limit, offset))[0]
    context = dict(reports=reports, permalinks=permalinks, form=form)
    return templates.TemplateResponse(req, 'feed.jinja', context)

def query_description(**kw) -> str:
    params = {k: v for k, v in kw.items() if v}
    return ' '.join(urlencode(params).split('&'))

def id_encode(**kw) -> str:
    params = {k: kw[k] for k in sorted(kw) if kw[k]}
    q = urlencode(params)
    return base64.b32hexencode(q.encode()).decode().lower()

def id_decode(id: str) -> dict[str, str]:
    q = base64.b32hexdecode(id, casefold=True).decode()
    params = parse_qs(q)
    return {k: v[0] for k, v in params.items()}

def id_permalink(id: str, fmt: str) -> str:
    return '/'.join((f'{settings.SITE_URL}/feed/{fmt}', id)).rstrip('/')
