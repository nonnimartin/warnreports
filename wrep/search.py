from __future__ import annotations

import dataclasses
import re
from typing import Any, Iterable, Iterator, Literal, Sequence

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.operations import IndexModel

from . import orm, settings, utils
from .backends.mongo import (AbstractCollection, AbstractMongoCollection,
                             MongoClient, MongoFilter, MongoQueryFilter,
                             Search, filters)
from .models import *

__all__ = ['filters', 'Search']

logger = utils.get_logger('search')

client = MongoClient(
    url=settings.SEARCH_MONGODB_URL,
    control_dbname=settings.SEARCH_MONGODB_CONTROL_DBNAME,
    dbname_key='search.dbname',
    dbname_ttl=settings.SEARCH_MONGODB_DBNAME_TTL,
    dbname_default=settings.SEARCH_MONGODB_DBNAME)

class AbstractMappedCollection(AbstractCollection):
    orm_model: type[orm.MapReduceBase]

@dataclasses.dataclass
class MappedCollection(AbstractMongoCollection, AbstractMappedCollection):
    client: MongoClient
    name: str
    orm_model: type[orm.MapReduceBase]
    data_model: type[DataModel] = None
    indexes: list[IndexModel] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.data_model = self.data_model or self.orm_model.data_model
        self.indexes = list(map(IndexModel, self.indexes))

    async def build(self, db: str|AsyncIOMotorDatabase|None = None, lazy: bool = True) -> None:
        'Build collection'
        db = await self.client.get_database(db)
        await self.clean(db=db)
        await self.init(db=db)
        with orm.SessionLocal() as session:
            logger.info(f'Building {self.name}')
            it = self.orm_model.map_reduce_exec(session, lazy=lazy)
            if self.data_model is not self.orm_model.data_model:
                it = map(self.data_model.model_validate, it)
            it = map(self.data_model.as_doc, it)
            await db.get_collection(self.name).insert_many(it)
        stat = await self.stats(db=db)
        logger.info(f'Built {self.name} {stat=}')

mapped_collections: dict[str, MappedCollection] = dict(
    reports=MappedCollection(
        client=client,
        name='reports',
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
    companies=MappedCollection(
        client=client,
        name='companies',
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
            {'employees_sum': -1}]),
    naics=MappedCollection(
        client=client,
        name='naics',
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
    artifacts=MappedCollection(
        client=client,
        name='artifacts',
        orm_model=orm.Artifact,
        indexes=[
            {'name': 1},
            {'path': 1}]),
    states=MappedCollection(
        client=client,
        name='states',
        orm_model=orm.StateStat,
        indexes=[
            {'id': 1},
            {'last_reported': -1},
            {'reports_count': -1}]))

class DefaultMongoFilter(MongoFilter):
    minmax_fields: ClassVar[Sequence[str]] = ()
    MINMAX_OPERS: ClassVar[dict[str, str]] = dict(min='$gte', max='$lte')

    def get_filters(self) -> Iterable[dict[str, Any]]:
        yield from self.get_minmax_filters(*self.minmax_fields)

    @staticmethod
    def wc_contains(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'.*{re.escape(text)}.*', flags)

    @staticmethod
    def wc_startswith(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'^{re.escape(text)}.*', flags)

    @classmethod
    def get_naics_filter(cls, naics: list[int], prefix: str = 'naics') -> dict[Literal['$or'], list[dict[str, Any]]]:
        if prefix:
            prefix = prefix.removesuffix('.') + '.'
        rxs = (
            {f'{prefix}code': {'$regex': cls.wc_startswith(str(code))}}
            for code in naics)
        return {'$or': [*rxs, {f'{prefix}id': {'$in': naics}}]}

    def get_minmax_filters(self, *fields: str) -> Iterator[dict[str, dict[str, int]]]:
        for field in fields:
            for suffix, oper in self.MINMAX_OPERS.items():
                if (value := getattr(self, f'{field}_{suffix}')) is not None:
                    yield {field: {oper: value}}

class MongoReportsFilter(ReportsFilter, DefaultMongoFilter):
    collection: ClassVar = mapped_collections['reports']
    minmax_fields: ClassVar = ('reported', 'starting', 'employees')

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.id_not:
            yield {'_id': {'$nin': self.id_not}}
        for field in ('state', 'company', 'company_id'):
            if (value := getattr(self, field)) is not None:
                yield {field: {'$in': value}}
        for field in ('action', 'location'):
            if (value := getattr(self, field)) is not None:
                yield {field: {'$regex': self.wc_contains(value)}}
        if self.naics is not None:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from super().get_filters()

class MongoStatesFilter(StatesFilter, DefaultMongoFilter):
    collection: ClassVar = mapped_collections['states']
    minmax_fields: ClassVar = ('reports_count', 'last_reported')

    def get_filters(self):
        if self.id:
            yield {'id': {'$in': sorted(set(map(str.upper, self.id)))}}
        yield from super().get_filters()

class MongoCompaniesFilter(CompaniesFilter, DefaultMongoFilter):
    collection: ClassVar = mapped_collections['companies']
    minmax_fields: ClassVar = MongoStatesFilter.minmax_fields + ('states_count', 'employees_sum')

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.name is not None:
            yield {'aliases': {'$in': self.name}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        if self.naics is not None:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from super().get_filters()

class MongoNaicsFilter(NaicsFilter, DefaultMongoFilter):
    collection: ClassVar = mapped_collections['naics']
    minmax_fields: ClassVar = MongoCompaniesFilter.minmax_fields + ('depth', 'companies_count')

    def get_filters(self):
        if self.id:
            yield {'id': {'$in': self.id}}
        if self.prefix is not None:
            yield self.get_naics_filter(self.prefix, prefix='')
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        if self.parent is not None:
            yield {'parent': {'$in': self.parent}}
        if self.root:
            yield {'root': {'$in': self.root}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        if self.is_leaf is not None:
            yield {'is_leaf': self.is_leaf}
        if self.includes:
            incs = set()
            for code in self.includes:
                s = str(code)
                for i in range(2, min(6, len(s))):
                    incs.add(int(s[:i]))
                incs.add(code)
            yield {'id': {'$in': sorted(incs)}}
        yield from super().get_filters()

class MongoArtifactsFilter(ArtifactsFilter, DefaultMongoFilter):
    collection: ClassVar = mapped_collections['artifacts']

    def get_filters(self):
        if self.id:
            yield {'_id': {'$in': self.id}}
        if self.state:
            it = (re.escape(x.lower()[:2]) for x in self.state)
            pat = '|'.join(filter(None, dict.fromkeys(it))) or '_'
            pat = f'^({pat})/.*'
            yield {'path': {'$regex': re.compile(pat)}}
        for field in ('name', 'sha1'):
            value = getattr(self, field)
            if value:
                yield {field: value}
        yield from super().get_filters()

from .backends import etl

class MongoExtractionFilter(ExtractionFilter, MongoQueryFilter):
    collection: ClassVar = etl.collections['extractions']

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        yield from super().get_filters()

class MongoTranslationFilter(TranslationFilter, MongoQueryFilter):
    collection: ClassVar = etl.collections['translations']

    def get_filters(self):
        if self.id is not None:
            yield {'id': {'$in': self.id}}
        if self.state is not None:
            yield {'states': {'$in': self.state}}
        yield from super().get_filters()

class MongoPipelineLogFilter(PipelineLogFilter, MongoQueryFilter):
    collection: ClassVar = etl.collections['pipelinelogs']
    minmax_fields: ClassVar = ('start', 'end', 'elapsed', 'errors_count')

    def get_filters(self):
        if self.id is not None:
            yield {'_id': {'$in': self.id}}
        if self.states is not None:
            yield {'states': {'$in': self.states}}
        if self.stages is not None:
            yield {'stages': {'$in': self.stages}}
        yield from super().get_filters()
