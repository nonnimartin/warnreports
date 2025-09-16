from __future__ import annotations

import json
from datetime import timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import BeforeValidator, Field

from .. import utils
from .base import AppCommand, AppCommandOpts

if TYPE_CHECKING:
    from ..backends.mongo import MongoClient

TtlOpt = Annotated[
    timedelta,
    BeforeValidator(utils.deltaopt('seconds')),
    Field(description='The TTL')]

class SetOpts(AppCommandOpts):
    name: str = Field(description='The database name')
    ttl: TtlOpt|None = Field(description='Override the TTL')

class TtlOpts(AppCommandOpts):
    ttl: TtlOpt

class ControlBase[O: AppCommandOpts](AppCommand[O]):
    dbname_key: ClassVar[str]
    client: MongoClient

class ControlGet(ControlBase[AppCommandOpts]):
    'Get the mongo control doc for {cls.dbname_key}'

    async def run(self):
        doc = await self.client.get_doc()
        print(json.dumps(doc, indent=2, default=str))

class ControlSet(ControlBase[SetOpts]):
    'Update the mongo control doc for {cls.dbname_key}'
    options_class: ClassVar = SetOpts

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('--ttl')
        arg('name')
        super().add_arguments(parser)

    async def run(self):
        doc = await self.client.set_dbname(self.opts.name, ttl=self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

class ControlTtl(ControlBase[TtlOpts]):
    'Update the mongo control doc TTL only for {cls.dbname_key}'
    options_class: ClassVar = TtlOpts

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('ttl')
        super().add_arguments(parser)

    async def run(self):
        doc = await self.client.set_ttl(self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

def makecommands(clientpath: str, dbname_key: str) -> dict[str, str|type[ControlBase]]:
    modname, attr = clientpath.rsplit('.', 1)
    modname = __package__.rsplit('.', 1)[0] + f'.{modname}'

    def getclient(_):
        import importlib
        mod = importlib.import_module(modname)
        return getattr(mod, attr)

    ns = dict(
        client=cached_property(getclient),
        dbname_key=dbname_key)
    return dict(
        _description=f'Mongo control doc commands for {dbname_key}',
        **{
            name: type(cls.__name__, (cls,), ns)
            for name, cls in [
                ('get', ControlGet),
                ('set', ControlGet),
                ('ttl', ControlTtl)]})
