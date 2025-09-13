from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

from .. import search
from .base import AppCommand, BaseCommand
from .mongo import ClientControlCommand

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    'Search collection commands'

    class Base(AppCommand):
        method: ClassVar[str]

        @classmethod
        def add_arguments(cls, parser):
            arg = parser.add_argument
            arg('--dbname', '-d',
                default=None,
                help=f'Alternate mongo search db name')
            if cls.method == 'build':
                arg('--eager', '-e',
                    action='store_false',
                    dest='lazy',
                    help='Use eager loading of SQL result sets. Uses more memory.')
            arg('names',
                nargs='*',
                choices=search.mapped_collections,
                help='Collection names, default all')
            super().add_arguments(parser)

        def setup(self, opts):
            super().setup(opts)
            self.names = self.opts.names or search.mapped_collections
            self.funckw = {}
            if hasattr(opts, 'lazy'):
                self.funckw.update(lazy=opts.lazy)

        async def run(self):
            if self.opts.dbname:
                logger.info(f'Using search dbname={self.opts.dbname}')
            db = await search.default_client.get_database(self.opts.dbname)
            results: dict[str, Any] = {}
            for name in self.names:
                defn = search.mapped_collections[name]
                res = await getattr(defn, self.method)(db=db, **self.funckw)
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
