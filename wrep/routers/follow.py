from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import utils
from ..models import *

router = APIRouter()
templates = Jinja2Templates(env=utils.jinja_env())

@router.get('/new')
async def form(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'follow.jinja')

@router.post('/new')
async def create(data: FollowData) -> FollowData:
    try:
        follow = Follow.get_or_create(**vars(data))[0]
    except IntegrityError:
        raise HTTPException(status_code=409, detail='409 Conflict')
    if not follow.confirmed:
        follow.send_confirm_email()
    return follow

@router.get('/confirm')
async def confirm(email: EmailStr, token: Token) -> SuccessData:
    follow = auth(email, token)
    if not follow.confirmed:
        follow.confirmed = utils.now()
        follow.save()
    return {}

@router.get('/cancel')
async def cancel(email: EmailStr, token: Token) -> SuccessData:
    follow = auth(email, token)
    follow.delete_instance()
    return {}


def auth(email: EmailStr, token: Token) -> Follow:
    try:
        return Follow.get(email=email, token=token)
    except Follow.DoesNotExist:
        raise HTTPException(status_code=401, detail='401 Unauthorized')
