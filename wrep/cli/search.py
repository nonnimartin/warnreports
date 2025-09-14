from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from pydantic import Field

from .. import search
from .base import AppCommand, BaseCommand, AppCommandOpts
from .mongo import ClientControlCommand

logger = logging.getLogger(__name__)

class SearchCommandOpts(AppCommandOpts):
    dbname: str|None = Field(
        default=None,
        description=f'Alternate mongo search db name')
    names: list[str] = Field(
        default_factory=list,
        description='Collection names, default all')

class Command(BaseCommand):
    'Search collection commands'

    class Base(AppCommand[SearchCommandOpts]):
        method: ClassVar[str]
        options_class: ClassVar = SearchCommandOpts

        @classmethod
        def add_arguments(cls, parser):
            arg = parser.add_argument
            arg('--dbname', '-d', metavar='<db>')
            arg('names', nargs='*', choices=search.mapped_collections)
            super().add_arguments(parser)

        def setup(self):
            super().setup()
            self.names = self.opts.names or search.mapped_collections

        async def run(self):
            if self.opts.dbname:
                logger.info(f'Using search dbname={self.opts.dbname}')
            db = await search.default_client.get_database(self.opts.dbname)
            results: dict[str, Any] = {}
            for name in self.names:
                defn = search.mapped_collections[name]
                res = await getattr(defn, self.method)(db=db)
                if res is not None:
                    results[name] = res
            if res:
                print(json.dumps(results, indent=2))

    def Collection(method: str, base=Base) -> type[Command.Base]:
        return type(f'{method}_Command', (base,), dict(
            method=method,
            description=getattr(search.MappedCollection, method).__doc__))

    commands = dict(
        stats=Collection('stats'),
        init=Collection('init'),
        build=Collection('build'),
        clean=Collection('clean'),
        control=ClientControlCommand(search.default_client))
