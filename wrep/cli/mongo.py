from __future__ import annotations

import json
from typing import Self

from .. import utils
from ..backends.mongo import MongoClient
from .base import AppCommand, BaseCommand


class ControlBaseCommand(AppCommand):
    client: MongoClient

    @classmethod
    def parser_fmtargs(cls, parser):
        return super().parser_fmtargs(parser) | dict(client=cls.client)

    @classmethod
    def fromclient(cls, client: MongoClient) -> type[Self]:
        return type(cls.__name__, (cls,), dict(client=client))

class ControlGetCommand(ControlBaseCommand):
    'Get the mongo control doc for {client.dbname_key}'

    async def run(self):
        doc = await self.client.get_doc()
        print(json.dumps(doc, indent=2, default=str))

class ControlSetCommand(ControlBaseCommand):
    'Update the mongo control doc for {client.dbname_key}'

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            '--ttl',
            type=utils.deltaopt('seconds'),
            default=None,
            help='Override the TTL')
        arg(
            'name',
            help='The database name')
        super().add_arguments(parser)

    async def run(self):
        doc = await self.client.set_dbname(self.opts.name, ttl=self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

class ControlTtlCommand(ControlBaseCommand):
    'Update the mongo control doc TTL only for {client.dbname_key}'

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            'ttl',
            type=utils.deltaopt('seconds'),
            help='The TTL')
        super().add_arguments(parser)

    async def run(self):
        doc = await self.client.set_ttl(self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

def ClientControlCommand(client: MongoClient) -> type[BaseCommand]:
    return type('MongoClientControlCommand', (BaseCommand,), dict(
        __doc__=f'Mongo control doc commands for {client.dbname_key}',
        commands=dict(
            get=ControlGetCommand.fromclient(client),
            set=ControlSetCommand.fromclient(client),
            ttl=ControlTtlCommand.fromclient(client))))
