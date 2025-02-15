from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import timedelta, timezone
from typing import Any, Self

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .. import settings, utils

logger = utils.get_logger('backends.mongo')

@dataclasses.dataclass
class MongoClient:
    """
    This manages the default/active database using a separate control database.
    This allows preparing clean indexes, and then switching to the new database
    on all produdction nodes without downtime.

    The value is cached in memory on each node, and is refreshed according to the TTL.
    If the control document does not exist, it is created using the default name setting.
    Alternatively, to require the document to exist, set the default name to '_'. This
    helps avoid returning empty results in due to misconfiguration.

    To perform an "atomic" switchover, first set a TTL of 0 with the current database name.
    This causes nodes to check the control document before each request. Wait for all nodes
    to pick up the TTL, according to the prior TTL value. Then update the control document.

    See commands `wrep search control` and `wrep etl control`.
    """
    url: str
    control_dbname: str
    dbname_key: str
    dbname_ttl: timedelta
    dbname_default: str

    def __post_init__(self) -> None:
        self.client = AsyncIOMotorClient(self.url, uuidRepresentation='standard')
        self.dbname_cache = dict(name=None, expiry=None)
        self.doc_id = uuid.uuid5(settings.NAMESPACE, self.dbname_key)
        self.control_db = self.client.get_database(self.control_dbname)
        self.dbname_ttl = utils.deltaparse(self.dbname_ttl, default_unit='seconds')

    async def get_database(self, db: str|AsyncIOMotorDatabase|None = None) -> AsyncIOMotorDatabase:
        if isinstance(db, AsyncIOMotorDatabase):
            return db
        db = db or await self.get_default_database_name()
        return self.client.get_database(db)

    async def get_default_database_name(self) -> str:
        now = utils.now(tz=timezone.utc)
        if self.dbname_cache['name'] and self.dbname_cache['expiry'] > now:
            return self.dbname_cache['name']
        doc = await self.get_doc()
        dbname = doc['value']
        if dbname != self.dbname_cache['name']:
            if self.dbname_cache['name']:
                logger.info(f'Selecting NEW {self.dbname_key}={dbname}')
            else:
                logger.info(f'Using {self.dbname_key}={dbname}')
            self.dbname_cache['name'] = dbname
        ttl = utils.deltaparse(doc.get('ttl', self.dbname_ttl), default_unit='seconds')
        self.dbname_cache['expiry'] = now + ttl
        return dbname

    async def get_doc(self) -> dict[str, Any]:
        'Get the control document'
        doc = await self.control_db.settings.find_one({'_id': self.doc_id})
        if not doc:
            if self.dbname_default == '_':
                raise MissingControlDoc(self.dbname_key, self.doc_id)
            doc = await self.set_dbname(self.dbname_default)
        return doc

    async def set_dbname(self, dbname: str, ttl: utils.Delta|None = None) -> dict[str, Any]:
        'Set the control dbname'
        now = utils.now(tz=timezone.utc)
        doc = dict(
            _id=self.doc_id,
            key=self.dbname_key,
            value=dbname,
            dbid=uuid.uuid5(settings.NAMESPACE, f'dbid:{dbname}'),
            updated=now)
        if ttl is None:
            ttl = self.dbname_ttl
        else:
            ttl = utils.deltaparse(ttl, default_unit='seconds')
            doc['ttl'] = f'{int(ttl.total_seconds())}s'
        res = await self.control_db.settings.replace_one(
            {'_id': self.doc_id},
            doc,
            upsert=True)
        if res.did_upsert:
            logger.info(f'Creating control setting {doc}')
        else:
            logger.info(f'Updated control setting {doc}')
        self.dbname_cache['name'] = dbname
        self.dbname_cache['expiry'] = now + ttl
        return doc

    async def set_ttl(self, ttl: utils.Delta) -> dict[str, Any]:
        'Set the control TTL only'
        ttl = utils.deltaparse(ttl, default_unit='seconds')
        now = utils.now(tz=timezone.utc)
        doc = await self.get_doc()
        doc.update(
            ttl=f'{int(ttl.total_seconds())}s',
            dbid=uuid.uuid5(settings.NAMESPACE, f'dbid:{doc['value']}'),
            updated=now)
        await self.control_db.settings.replace_one({'_id': self.doc_id}, doc)
        self.dbname_cache['expiry'] = now + ttl
        return doc

class MissingControlDoc(Exception):
    pass


class ControlBaseCommand(utils.BaseCommand):
    mongo: MongoClient

    @classmethod
    def parser_fmtargs(cls, parser):
        return super().parser_fmtargs(parser) | dict(client=cls.mongo)

    @classmethod
    def fromclient(cls, client: MongoClient) -> type[Self]:
        return type(cls.__name__, (cls,), dict(mongo=client))

class ControlGetCommand(ControlBaseCommand):
    'Get the mongo control doc for {client.dbname_key}'

    async def run(self):
        doc = await self.mongo.get_doc()
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

    async def run(self):
        doc = await self.mongo.set_dbname(self.opts.name, ttl=self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

class ControlTtlCommand(ControlBaseCommand):
    'Update the mongo control doc TTL only for {client.dbname_key}'

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            'ttl',
            type=utils.deltaopt('seconds'),
            help='The TTL')

    async def run(self):
        doc = await self.mongo.set_ttl(self.opts.ttl)
        print(json.dumps(doc, indent=2, default=str))

def ClientControlCommand(client: MongoClient) -> type[utils.BaseCommand]:
    return type('MongoClientControlCommand', (utils.BaseCommand,), dict(
        __doc__=f'Mongo control doc commands for {client.dbname_key}',
        commands=dict(
            get=ControlGetCommand.fromclient(client),
            set=ControlSetCommand.fromclient(client),
            ttl=ControlTtlCommand.fromclient(client))))
