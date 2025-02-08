from __future__ import annotations

import dataclasses
import uuid
from datetime import timedelta
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .. import settings, utils

logger = utils.get_logger('search')

@dataclasses.dataclass
class MongoClient:
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

    async def get_database(self, db: str|AsyncIOMotorDatabase|None = None) -> AsyncIOMotorDatabase:
        if isinstance(db, AsyncIOMotorDatabase):
            return db
        db = db or await self.get_default_database_name()
        return self.client.get_database(db)

    async def get_default_database_name(self) -> str:
        now = utils.now()
        if self.dbname_cache['name'] and self.dbname_cache['expiry'] > now:
            return self.dbname_cache['name']
        doc = await self.get_doc()
        dbname = doc['value']
        if dbname != self.dbname_cache['name']:
            logger.info(f'Selecting new search DB {dbname=}')
            self.dbname_cache['name'] = dbname
        ttl = utils.deltaparse(doc.get('ttl', self.dbname_ttl), default_unit='seconds')
        self.dbname_cache['expiry'] = now + ttl
        return dbname

    async def get_doc(self) -> dict[str, Any]:
        'Get the control document'
        doc = await self.control_db.settings.find_one({'_id': self.doc_id})
        if not doc:
            if self.dbname_default == '_':
                raise MissingControlDoc
            doc = await self.set_dbname(self.dbname_default)
        return doc

    async def set_dbname(self, dbname: str, ttl: utils.Delta|None = None) -> dict[str, Any]:
        'Set the control dbname'
        doc = dict(_id=self.doc_id, key=self.dbname_key, value=dbname)
        if ttl is not None:
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
        return doc

class MissingControlDoc(Exception):
    pass