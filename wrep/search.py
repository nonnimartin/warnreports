from __future__ import annotations

import dataclasses
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.operations import IndexModel

from . import orm, settings
from .backends.mongo import (AbstractCollection, AbstractMongoCollection,
                             MongoClient, MongoFilterModel)
from .models import *

__all__ = ['mapped_collections']

logger = logging.getLogger(__name__)

default_client = MongoClient(
    url=settings.SEARCH_MONGODB_URL,
    control_dbname=settings.SEARCH_MONGODB_CONTROL_DBNAME,
    dbname_key=settings.SEARCH_MONGODB_DBNAME_KEY,
    dbname_ttl=settings.SEARCH_MONGODB_DBNAME_TTL,
    dbname_default=settings.SEARCH_MONGODB_DBNAME)

class AbstractMappedCollection(AbstractCollection):
    orm_model: type[orm.MapReduceBase]

@dataclasses.dataclass(kw_only=True)
class MappedCollection(AbstractMongoCollection, AbstractMappedCollection):
    name: str
    client: MongoClient
    orm_model: type[orm.MapReduceBase]
    indexes: list[IndexModel] = dataclasses.field(default_factory=list)

    @property
    def data_model(self) -> type[DataModel]:
        return self.orm_model.data_model

    def __post_init__(self) -> None:
        self.indexes = list(map(IndexModel, self.indexes))

    async def build(self, *, db: str|AsyncIOMotorDatabase|None = None, client: MongoClient|None = None, session: orm.Session|None = None, lazy: bool = True) -> None:
        'Build collection'
        client = client or self.client
        db = await client.get_database(db)
        await self.clean(db=db, client=client)
        await self.init(db=db, client=client)
        with orm.ensure_session(session) as session:
            logger.info(f'Building {self.name}')
            it = self.orm_model.map_reduce_exec(session, lazy=lazy)
            if self.data_model is not self.orm_model.data_model:
                it = map(self.data_model.model_validate, it)
            it = (x.model_dump(by_alias=True) for x in it)
            await db.get_collection(self.name).insert_many(it)
        stat = await self.stats(db=db, client=client)
        logger.info(f'Built {self.name} {stat=}')

mapped_collections: dict[str, MappedCollection] = {
    collection.name: collection for collection in [
    MappedCollection(
        name='reports',
        client=default_client,
        orm_model=orm.Report,
        indexes=[
            {'company': 'text'},
            {'company_id': 1},
            {'reported': 1},
            {'reported': -1},
            {'employees': 1},
            {'employees': -1},
            {'naics.code': 1},
            {'naics.id': 1},
            {'state': 1}]),
    MappedCollection(
        name='companies',
        client=default_client,
        orm_model=orm.Company,
        indexes=[
            {'aliases': 'text'},
            {'name': 1},
            {'aliases': 1},
            {'states': 1},
            {'naics.code': 1},
            {'naics.id': 1},
            {'last_reported': 1},
            {'last_reported': -1},
            {'reports_count': 1},
            {'reports_count': -1},
            {'states_count': 1},
            {'states_count': -1},
            {'aliases_count': 1},
            {'aliases_count': -1},
            {'employees_sum': -1}]),
    MappedCollection(
        name='naics',
        client=default_client,
        orm_model=orm.Naics,
        indexes=[
            {'id': 1},
            {'code': 1},
            {'title': 1},
            {'root': 1},
            {'parent': 1},
            {'depth': 1},
            {'states': 1},
            {'is_leaf': 1},
            {'companies_count': 1},
            {'last_reported': 1},
            {'last_reported': -1},
            {'reports_count': 1},
            {'reports_count': -1},
            {'states_count': 1},
            {'states_count': -1},
            {'employees_sum': -1}]),
    MappedCollection(
        name='artifacts',
        client=default_client,
        orm_model=orm.Artifact,
        indexes=[
            {'name': 1},
            {'path': 1},
            {'state': 1},
            {'sha1': 1}]),
    MappedCollection(
        name='states',
        client=default_client,
        orm_model=orm.StateStat,
        indexes=[
            {'id': 1},
            {'last_reported': -1},
            {'reports_count': -1}])]}

class MongoReportsFilter(ReportsFilter, MongoFilterModel[ReportData]):
    collection: ClassVar = mapped_collections['reports']

class MongoStatesFilter(StatesFilter, MongoFilterModel[StateDetail]):
    collection: ClassVar = mapped_collections['states']

class MongoCompaniesFilter(CompaniesFilter, MongoFilterModel[CompanyDetail]):
    collection: ClassVar = mapped_collections['companies']

class MongoNaicsFilter(NaicsFilter, MongoFilterModel[NaicsDetail]):
    collection: ClassVar = mapped_collections['naics']

class MongoArtifactsFilter(ArtifactsFilter, MongoFilterModel[ArtifactDetail]):
    collection: ClassVar = mapped_collections['artifacts']
