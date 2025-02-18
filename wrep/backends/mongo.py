from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import timedelta, timezone
from typing import Any, AsyncIterator, ClassVar, Iterable, Self

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)
from pydantic import Field
from pymongo.operations import IndexModel

from .. import settings, utils
from ..models import DataModel, FilterModel, Limit, Offset

type FilterType[DM: DataModel] = MongoFilter|FilterModel[DM]
type FiltersType[DM: DataModel] = dict[type[DM], type[FilterType[DM]]]
logger = utils.get_logger('backends.mongo')
filters: FiltersType = {}

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

class AbstractCollection:
    name: str
    data_model: type[DataModel]

class AbstractMongoCollection(AbstractCollection):
    indexes: list[IndexModel]
    client: MongoClient

    async def stats(self, db: str|AsyncIOMotorDatabase|None = None) -> dict[str, str|int]:
        'Get collection stats'
        db = await self.client.get_database(db)
        stat = await db.command('collstats', self.name)
        return dict(name=self.name, count=stat['count'], size=stat['size'])

    async def init(self, db: str|AsyncIOMotorDatabase|None = None) -> None:
        'Init collection'
        db = await self.client.get_database(db)
        logger.info(f'Initializing {self.name}')
        await db.get_collection(self.name).create_indexes(self.indexes)

    async def clean(self, db: str|AsyncIOMotorDatabase|None = None) -> None:
        'Clean collection'
        db = await self.client.get_database(db)
        stat = await self.stats(db=db)
        logger.info(f'Cleaning {self.name} {stat=}')
        await db.get_collection(self.name).drop()

@dataclasses.dataclass
class MongoCollection(AbstractMongoCollection):
    client: MongoClient
    name: str
    data_model: type[DataModel]|None = None
    indexes: list[IndexModel] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.indexes = list(map(IndexModel, self.indexes))

class MongoFilter:
    collection: ClassVar[AbstractMongoCollection]

    def get_query(self) -> dict[str, Any]:
        filts = tuple(self.get_filters())
        return {'$and': filts} if filts else {}

    def get_filters(self) -> Iterable[dict[str, Any]]:
        yield from ()

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)
        if (model := getattr(cls, 'result_model', None)):
            if issubclass(model, DataModel):
                filters[model] = cls

class MongoQueryFilter(MongoFilter):
    q: dict[str, Any] = Field(default_factory=dict)

    def get_filters(self):
        if self.q:
            yield self.q

@dataclasses.dataclass
class Search[DM: DataModel]:
    filter: FilterType[DM]
    limit: Limit|None = None
    offset: Offset = 0
    dbname: str|None = None

    @property
    def model(self) -> type[DM]:
        return self.filter.result_model

    @property
    def collection(self) -> AbstractMongoCollection:
        return self.filter.collection

    @property
    def client(self) -> MongoClient:
        return self.collection.client

    @utils.lazyprop
    def q(self) -> dict[str, Any]:
        return self.filter.get_query()

    def __post_init__(self) -> None:
        if self.limit == 0:
            self.orders = []
        else:
            self.orders = list(self.filter.get_ordering())
            if ('_id', 1) not in self.orders and ('_id', -1) not in self.orders:
                self.orders.append(('_id', 1))
        self._db = None

    async def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            self._db = await self.client.get_database(self.dbname)
        return self._db

    async def get_collection(self) -> AsyncIOMotorCollection:
        return (await self.db()).get_collection(self.collection.name)

    async def count(self) -> int:
        if settings.QUERY_LOGGING:
            logger.info(f'COUNT q={self.q}')
        return await (await self.get_collection()).count_documents(self.q)

    async def tolist(self) -> list[DM]:
        return [obj async for obj in self.objs()]

    async def objs(self) -> AsyncIterator[DM]:
        to_model = self.model.model_validate
        async for doc in await self.docs():
            yield to_model(doc)

    async def docs(self) -> AsyncIterator[dict[str, Any]]:
        if self.limit == 0:
            return utils.as_aiter(())
        if settings.QUERY_LOGGING:
            logger.info(f'FIND q={self.q}')
        cur = (await self.get_collection()).find(self.q)
        if self.orders:
            cur = cur.sort(self.orders)
        if self.offset:
            cur = cur.skip(self.offset)
        if self.limit is not None:
            cur = cur.limit(self.limit)
        return cur

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
