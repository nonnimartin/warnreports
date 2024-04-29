from __future__ import annotations

from argparse import ArgumentParser
from uuid import uuid4
from urllib.parse import urlencode
import peewee as lib
from playhouse import db_url

import settings
import utils

db: lib.Database = db_url.connect(settings.DB_URL)


class Model(lib.Model):
    class Meta:
        database = db

class Company(Model):
    id = lib.UUIDField(primary_key=True, default=uuid4)
    name = lib.CharField(max_length=512, index=True, collation='NOCASE')
    state = lib.CharField(max_length=2, index=True, collation='NOCASE')

    class Meta:
        indexes = [
            (('name', 'state'), True),
        ]

class Report(Model):
    id = lib.UUIDField(primary_key=True, default=uuid4)
    company = lib.ForeignKeyField(Company)
    created = lib.DateTimeField(index=True, default=utils.now)
    location = lib.CharField(max_length=255, null=True, index=True, collation='NOCASE')
    reported = lib.DateTimeField(index=True)
    starting = lib.DateTimeField(index=True, null=True)
    employees = lib.IntegerField(null=True)
    action = lib.CharField(max_length=64, null=True, index=True)
    url = lib.CharField(max_length=255, null=True, index=True)

    class Meta:
        indexes = [
            (('company', 'location', 'reported', 'starting', 'employees', 'action'), True),
        ]

class Contact(Model):
    id = lib.UUIDField(primary_key=True, default=uuid4)
    email = lib.CharField(index=True, collation='NOCASE')
    company = lib.CharField(max_length=512, index=True, collation='NOCASE')
    state = lib.CharField(max_length=2, null=True, index=True, collation='NOCASE')
    created = lib.DateTimeField(index=True, default=utils.now)
    notified = lib.DateTimeField(null=True, index=True)
    confirmed = lib.DateTimeField(null=True, index=True)
    token = lib.CharField(max_length=64, unique=True)

    class Meta:
        indexes = [
            (('email', 'company', 'state'), True),
        ]

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = utils.uuid_token(self.id)
        return super().save(*args, **kwargs)

    def send_confirm_email(self) -> bool:
        context = dict(
            contact=self,
            confirm_url=self._auth_url('/confirm'),
            unsubscribe_url=self._auth_url('/unsubscribe'))
        return utils.send_email(
            recipient=self.email,
            subject='WARN Notices - Confirm Your Account',
            body=utils.render('confirm.jinja', context))

    def _auth_url(self, path: str) -> str:
        query = urlencode(dict(token=self.token, email=self.email))
        return f'{settings.SITE_URL}{path}?{query}'

def migrate():
    db.create_tables([Company, Report, Contact])

actions = dict(migrate=migrate)

def main():
    parser = ArgumentParser()
    parser.add_argument('action', choices=actions)
    opts = parser.parse_args()
    actions[opts.action]()

if __name__ == '__main__':
    utils.init_logging()
    main()
