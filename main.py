from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import settings
import utils
from models import *

app = FastAPI()
app.mount('/static', StaticFiles(directory=settings.STATIC_DIR), name='static')

@app.get('/reports')
async def reports_list(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    location: str|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[ReportData]:
    fields = ReportData.orm_fields(Report)
    filters = ReportData.filters(search, company, state, location)
    q = Report.select(*fields)
    q = q.where(*filters)
    q = q.order_by(
        Report.reported.desc(),
        Report.state.collate('NOCASE'),
        Report.company.collate('NOCASE'))
    q = q.limit(limit).offset(offset)
    return q

@app.get('/companies')
async def companies_list(
    search: str|None = None,
    company: str|None = None,
    state: State|None = None,
    limit: Limit = 50,
    offset: Offset = 0
) -> list[CompanyData]:
    fields = CompanyData.orm_fields(Report)
    filters = ReportData.filters(search, company, state)
    q = Report.select(*fields).distinct()
    q = q.where(*filters)
    q = q.order_by(Report.company.collate('NOCASE'))
    q = q.limit(limit).offset(offset)
    return q

@app.get('/states')
async def states_list() -> list[StateData]:
    fields = StateData.orm_fields(Report)
    q = Report.select(*fields).distinct()
    q = q.order_by(Report.state)
    return q

@app.post('/follow')
async def follow_create(data: FollowData) -> FollowData:
    try:
        follow = Follow.get_or_create(**vars(data))[0]
    except IntegrityError:
        raise HTTPException(status_code=409, detail='409 Conflict')
    if not follow.confirmed:
        follow.send_confirm_email()
    return follow

@app.get('/follow/confirm')
async def follow_confirm(email: EmailStr, token: Token) -> SuccessData:
    follow = authenticate(email, token)
    if not follow.confirmed:
        follow.confirmed = utils.now()
        follow.save()
    return {}

@app.get('/follow/cancel')
async def follow_cancel(email: EmailStr, token: Token) -> SuccessData:
    follow = authenticate(email, token)
    follow.delete_instance()
    return {}


def authenticate(email: EmailStr, token: Token) -> Follow:
    try:
        return Follow.get(email=email, token=token)
    except Follow.DoesNotExist:
        raise HTTPException(status_code=401, detail='401 Unauthorized')
