from __future__ import annotations

import enum
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, ClassVar

from pydantic import Field, field_validator

from .. import settings
from . import mongo
from .base import AppCommand, AppCommandOpts

logger = logging.getLogger(__name__)

class CollectionName(enum.StrEnum):
    reports = 'reports'
    companies = 'companies'
    artifacts = 'artifacts'
    naics = 'naics'
    states = 'states'

    def defn(self):
        from ..search import mapped_collections
        return mapped_collections[self]

class SearchOpts(AppCommandOpts):
    dbname: str|None = Field(
        default=None,
        description=f'Alternate mongo search db name')
    names: list[CollectionName] = Field(
        default_factory=list,
        description='Collection names, default all')

    @field_validator('names', mode='after')
    @classmethod
    def fillnames(cls, value) -> list[CollectionName]:
        return value or list(CollectionName)

class Base(AppCommand[SearchOpts]):
    method: ClassVar[str]
    options_class: ClassVar = SearchOpts

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--dbname', '-d', metavar='<db>')
        arg('names', nargs='*', choices=(...,))
        super().add_arguments(parser)

    async def run(self):
        if self.opts.dbname:
            logger.info(f'Using search dbname={self.opts.dbname}')
        results: dict[str, Any] = {}
        async with self.ctxkw() as kw:
            for name in self.opts.names:
                func = getattr(name.defn(), self.method)
                res = await func(**kw)
                if res is not None:
                    results[name] = res
        if results:
            print(json.dumps(results, indent=2))

    @asynccontextmanager
    async def ctxkw(self):
        from .. import search
        client = search.default_client
        db = await client.get_database(self.opts.dbname)
        kw = dict(db=db, client=client)
        if self.method == 'build':
            from ..orm import SessionLocal
            with SessionLocal() as session:
                kw.update(session=session)
                yield kw
        else:
            yield kw

def Collection(method: str, base=Base, description: str|None = None) -> type[Base]:
    return type(f'{method}_Command', (base,), dict(
        method=method,
        description=description))

commands = dict(
    _description='Search collection commands',
    stats=Collection('stats', description='Get collection stats'),
    init=Collection('init', description='Init collections'),
    build=Collection('build', description='Build collections'),
    clean=Collection('clean', description='Clean collections'),
    control=mongo.makecommands(
        'search.default_client',
        settings.SEARCH_MONGODB_DBNAME_KEY))
