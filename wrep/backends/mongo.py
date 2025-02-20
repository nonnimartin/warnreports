from __future__ import annotations

import dataclasses
import re
import uuid
from datetime import timedelta
from typing import Any, AsyncIterator, ClassVar, Iterable, Literal

from motor.motor_asyncio import (AsyncIOMotorClient, AsyncIOMotorCollection,
                                 AsyncIOMotorDatabase)
from pydantic import SerializationInfo, SerializerFunctionWrapHandler, model_serializer
from pymongo.operations import IndexModel

from .. import settings, utils
from ..models import DataModel, FilterModel, Limit, Offset, Fi

filters: dict[type[DataModel], type[FilterModel[DataModel]]] = {}
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

    async def get_context_database(self, context: dict[str, Any]) -> AsyncIOMotorDatabase:
        db = await self.get_database(context.get(self.dbname_key))
        context[self.dbname_key] = db.name
        return db

    async def get_default_database_name(self) -> str:
        now = utils.utcnow()
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
        now = utils.utcnow()
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
        now = utils.utcnow()
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
    data_model: type[DataModel]
    indexes: list[IndexModel] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.indexes = list(map(IndexModel, self.indexes))

class MongoFilterModel[DM: DataModel](FilterModel[DM]):
    collection: ClassVar[MongoCollection]

    def get_query(self):
        q = self.model_dump(context={'tofilter': True})
        if (filts := list(self.get_filters())):
            q.setdefault('$and', []).extend(filts)
        return q

    def get_filters(self) -> Iterable[dict[str, Any]]:
        yield from ()

    @model_serializer(mode='wrap')
    def serialize_filter(self, nxt: SerializerFunctionWrapHandler, info: SerializationInfo):
        if not (info.context and info.context.get('tofilter')):
            return nxt(self)
        result = {}
        prepped = []
        data = self.model_dump(exclude_none=True, exclude=['order'])
        for name, value in data.items():
            field = self.model_fields[name]
            if (meta := field.metadata) and isinstance(anno := meta[0], Fi):
                if anno.alias is None:
                    anno.alias = name
                if anno.oper == '$naics':
                    prepped.append(get_naics_filter(value, anno.alias))
                    continue
                if anno.oper == '$search':
                    name = '$text'
                elif anno.oper == '$contains':
                    anno.oper = '$regex'
                    value = wc_contains(value)
                prepped.append({anno.alias: {anno.oper: value}})
        if prepped:
            result['$and'] = prepped
        return result

    def __init_subclass__(cls, **kw) -> None:
        super().__init_subclass__(**kw)
        if (model := getattr(cls, 'result_model', None)):
            if issubclass(model, DataModel):
                filters[model] = cls

@dataclasses.dataclass
class Search[DM: DataModel]:
    filter: FilterModel[DM]|MongoFilterModel[DM]
    limit: Limit|None = None
    offset: Offset = 0
    context: dict[str, Any]|None = None

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
        if self.context is None:
            self.context = {}
        if self.limit == 0:
            self.orders = []
        else:
            self.orders = list(self.filter.get_ordering())
            if ('_id', 1) not in self.orders and ('_id', -1) not in self.orders:
                self.orders.append(('_id', 1))

    async def db(self) -> AsyncIOMotorDatabase:
        return await self.client.get_context_database(self.context)

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

def wc_contains(text: str) -> re.Pattern:
    return re.compile(f'.*{re.escape(text)}.*', re.I)

def wc_startswith(text: str) -> re.Pattern:
    return re.compile(f'^{re.escape(text)}.*', re.I)

def get_naics_filter(naics: list[int], prefix: str = 'naics') -> dict[Literal['$or'], list[dict[str, Any]]]:
    if prefix:
        prefix = prefix.removesuffix('.') + '.'
    rxs = (
        {f'{prefix}code': {'$regex': wc_startswith(str(code))}}
        for code in naics)
    return {'$or': [*rxs, {f'{prefix}id': {'$in': naics}}]}
