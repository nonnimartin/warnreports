from __future__ import annotations

import hashlib
import logging
from argparse import ArgumentParser
from uuid import uuid4, UUID

import peewee as lib
from playhouse import db_url

import settings
import utils

db: lib.Database = db_url.connect(settings.DB_URL)

def make_token(user_id: UUID) -> str:
    key = user_id.hex + settings.SEED
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

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
            self.token = make_token(self.id)
        return super().save(*args, **kwargs)

    @classmethod
    def validate_token(cls, email: str, token: str) -> bool:
        return bool(
            token and
            cls.get_or_none(
                cls.email == email,
                cls.token == token))

def migrate():
    db.create_tables([Company, Report, Contact])

parser = ArgumentParser()
parser.add_argument('action', choices=['migrate'])

def main():
    opts = parser.parse_args()
    if opts.action == 'migrate':
        migrate()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
