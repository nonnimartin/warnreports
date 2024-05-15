from __future__ import annotations

from typing import Literal, TypeAlias
from urllib.parse import urlencode
from uuid import UUID, uuid4

from playhouse import db_url
from pydantic import EmailStr

from wrep import utils
from wrep.models import *

from . import settings

__all__ = ['userdb', 'Token', 'EmailStr', 'Follow', 'FollowData']
userdb: orm.Database = db_url.connect(settings.USERS_DB_URL)

Token: TypeAlias = UUID

class Follow(orm.Model):
    id = orm.UUIDField(primary_key=True, default=uuid4)
    email = orm.CharField(index=True, collation='NOCASE')
    company = orm.CharField(max_length=512, index=True, collation='NOCASE')
    state = orm.CharField(max_length=2, index=True, default='*', collation='NOCASE')
    created = orm.DateTimeField(index=True, default=utils.now)
    notified = orm.DateTimeField(null=True, index=True)
    confirmed = orm.DateTimeField(null=True, index=True)
    token = orm.UUIDField(unique=True, default=uuid4)

    class Meta:
        database = userdb
        indexes = [(('email', 'company', 'state'), True)]

    @property
    def confirm_url(self) -> str:
        return self._auth_url('/follow/confirm')

    @property
    def cancel_url(self) -> str:
        return self._auth_url('/follow/cancel')

    def send_confirm_email(self) -> bool:
        return utils.send_email(
            recipient=self.email,
            subject='WARN Notices - Confirm Your Account',
            body=utils.render('email/confirm.jinja', follow=self))

    def _auth_url(self, path: str) -> str:
        query = urlencode(dict(token=self.token, email=self.email))
        return f'{settings.SITE_URL}{path}?{query}'

class FollowData(DataModel):
    email: EmailStr
    company: CompanyName
    state: StateCode|Literal['*'] = '*'