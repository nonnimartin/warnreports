from __future__ import annotations
from wrep import utils
from wrep.models import *
from .models import *
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(env=utils.jinja_env())

class SuccessData(DataModel):
    success: Literal[True] = True

@router.get('/new')
async def form(req: Request) -> HTMLResponse:
    return templates.TemplateResponse(req, 'follow.jinja')

@router.post('/new')
async def create(data: FollowData) -> FollowData:
    try:
        follow = Follow.get_or_create(**vars(data))[0]
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT)
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
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)