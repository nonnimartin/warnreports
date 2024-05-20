from __future__ import annotations

import re
from abc import abstractmethod
from typing import Any, ClassVar, Iterable, Iterator

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.operations import IndexModel

from . import settings, utils
from .models import *
from .models import MapReducingModel

__all__ = ['filters', 'mongo', 'retrieve', 'retrieve404', 'search', 'NotFoundError']

logger = utils.get_logger('search')


class MongoSearch(FilterModel[DM]):
    collection_name: ClassVar[str]

    @abstractmethod
    def get_filters(self) -> Iterable[Any]:
        yield from ()

    @staticmethod
    def wc_contains(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'.*{re.escape(text)}.*', flags)

    @staticmethod
    def wc_startswith(text: str, flags: re.RegexFlag = re.I) -> re.Pattern:
        return re.compile(f'^{re.escape(text)}.*', flags)

    @classmethod
    def get_naics_filter(cls, naics: int, prefix: str = 'naics'):
        if prefix:
            prefix = prefix.removesuffix('.') + '.'
        return {
                '$or': [
                    {f'{prefix}code': {'$regex': cls.wc_startswith(str(naics))}},
                    {f'{prefix}id': naics}]}

    def get_ltgt_filters(self, field: str, lt: str = 'lt', gt: str = 'gt') -> Iterator[dict[str, dict[str, int]]]:
        for oper, suffix in zip(('$lt', '$gt'), (lt, gt)):
            value = getattr(self, f'{field}_{suffix}')
            if value is not None:
                yield {field: {oper: value}}

class MongoReportsFilter(ReportsFilter, MongoSearch[ReportData]):
    collection_name: ClassVar = 'reports'

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        if self.state:
            yield {'state': self.state.upper()}
        if self.company:
            yield {'company': {'$regex': self.wc_contains(self.company)}}
        if self.action:
            yield {'action': {'$regex': self.wc_contains(self.action)}}
        if self.location:
            yield {'location': {'$regex': self.wc_contains(self.location)}}
        if self.naics:
            yield self.get_naics_filter(self.naics)
        if self.text:
            yield {'$text': {'$search': self.text}}
        yield from self.get_ltgt_filters('reported', 'before', 'after')
        yield from self.get_ltgt_filters('starting', 'before', 'after')
        yield from self.get_ltgt_filters('employees')

class MongoStatesFilter(StatesFilter, MongoSearch[StateDetail]):
    collection_name: ClassVar = 'states'

    def get_filters(self):
        if self.id:
            yield {'id': self.id.upper()}
        yield from self.get_ltgt_filters('reports_count')
        yield from self.get_ltgt_filters('last_reported', 'before', 'after')

class MongoCompaniesFilter(CompaniesFilter, MongoSearch[CompanyDetail]):
    collection_name: ClassVar = 'companies'

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        if self.name:
            yield {'name': {'$regex': self.wc_contains(self.name)}}
        if self.state:
            yield {'states': self.state.upper()}
        if self.naics:
            yield self.get_naics_filter(self.naics)
        yield from self.get_ltgt_filters('reports_count')
        yield from self.get_ltgt_filters('employees_sum')
        yield from self.get_ltgt_filters('last_reported', 'before', 'after')

class MongoNaicsFilter(NaicsFilter, MongoSearch[NaicsDetail]):
    collection_name: ClassVar = 'naics'

    def get_filters(self):
        if self.id:
            yield {'id': self.id}
        if self.code is not None:
            yield {'code': self.code}
        if self.prefix:
            yield self.get_naics_filter(self.prefix, prefix='')
        if self.title:
            yield {'title': {'$regex': self.wc_contains(self.title)}}
        yield from self.get_ltgt_filters('reports_count')
        yield from self.get_ltgt_filters('companies_count')

class MongoArtifactsFilter(ArtifactsFilter, MongoSearch[ArtifactDetail]):
    collection_name: ClassVar = 'artifacts'

    def get_filters(self):
        if self.id:
            yield {'_id': self.id}
        for field in ('name', 'sha1'):
            value = getattr(self, field)
            if value:
                yield {field: value}

class NotFoundError(Exception):
    pass

filters: dict[type[DataModel], type[MongoSearch]] = {
    ReportData: MongoReportsFilter,
    StateDetail: MongoStatesFilter,
    CompanyDetail: MongoCompaniesFilter,
    NaicsDetail: MongoNaicsFilter,
    ArtifactDetail: MongoArtifactsFilter}

async def search_result(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0,
    with_total: bool = False,
) -> tuple[list[DM], int|None]:
    filt = filters[model](**params or {})
    coll = mongo.get_collection(filt.collection_name)
    filts = tuple(filt.get_filters())
    q = {'$and': filts} if filts else {}
    cur = coll.find(q)
    orders = tuple(filt.get_ordering())
    if orders:
        cur = cur.sort(orders)
    if offset:
        cur = cur.skip(offset)
    if limit:
        cur = cur.limit(limit)
    total = await coll.count_documents(q) if with_total else None
    objs = [model.model_validate(obj) async for obj in cur]
    return objs, total

async def search_with_total(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> tuple[list[DM], int]:
    return await search_result(model, params, limit, offset, with_total=True)

async def search(
    model: type[DM],
    params: dict[str, Any]|None = None,
    limit: Limit|None = None,
    offset: Offset = 0
) -> list[DM]:
    return (await search_result(model, params, limit, offset))[0]

async def retrieve(model: type[DM], **params) -> DM:
    results = await search(model, params, 1)
    if results:
        return results[0]
    raise NotFoundError

async def retrieve404(model: type[DM], **params) -> DM:
    try:
        return await retrieve(model, **params)
    except NotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

mongo_client = AsyncIOMotorClient(settings.MONGODB_URL, uuidRepresentation='standard')
mongo = mongo_client.get_database(settings.MONGODB_DBNAME)

collection_defs = dict(
    reports=dict(
        model=ReportData,
        indexes=[
            IndexModel({'company': 'text'}),
            IndexModel({'reported': 1}),
            IndexModel({'reported': -1}),
            IndexModel({'employees': 1}),
            IndexModel({'employees': -1}),
            IndexModel({'naics.code': 1}),
            IndexModel({'naics.id': 1}),
            IndexModel({'state': 'hashed'}),
        ],
    ),
    states=dict(
        model=StateDetail,
        indexes=[
            IndexModel({'id': 'hashed'}),
            IndexModel({'last_reported': -1}),
            IndexModel({'reports_count': -1}),
        ],
    ),
    companies=dict(
        model=CompanyDetail,
        indexes=[
            IndexModel({'name': 1}),
            IndexModel({'states': 1}),
            IndexModel({'naics.code': 1}),
            IndexModel({'naics.id': 1}),
            IndexModel({'last_reported': 1}),
            IndexModel({'last_reported': -1}),
            IndexModel({'reports_count': 1}),
            IndexModel({'reports_count': -1}),
        ],
    ),
    artifacts=dict(
        model=ArtifactDetail,
        indexes=[
            IndexModel({'name': 1}),
        ],
    ),
    naics=dict(
        model=NaicsDetail,
        indexes=[
            IndexModel({'id': 'hashed'}),
            IndexModel({'id': 1}),
            IndexModel({'code': 1}),
            IndexModel({'title': 1}),
            IndexModel({'companies_count': 1}),
            IndexModel({'reports_count': 1}),
            IndexModel({'reports_count': -1}),
        ],
    ),
)

async def search_stats(*names: str) -> dict[str, dict[str, Any]]:
    names = names or collection_defs
    stats = {}
    for name in names:
        stats[name] = await mongo.command('collstats', name)
    return stats

async def search_init(*names: str) -> None:
    names = names or collection_defs
    for name in names:
        indexes = collection_defs[name]['indexes']
        await mongo.get_collection(name).create_indexes(indexes)

async def search_clean(*names: str) -> None:
    names = names or collection_defs
    for name in names:
        await mongo.get_collection(name).drop()

async def search_build(*names: str) -> None:
    names = names or collection_defs
    await search_clean(*names)
    await search_init(*names)
    for name in names:
        defn = collection_defs[name]
        model: type[MapReducingModel] = defn['model']
        it = map(model.as_doc, model.map_reduce())
        await mongo.get_collection(name).insert_many(it)

actions = dict(
    init=search_init,
    build=search_build,
    clean=search_clean)

class Command(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser) -> None:
        parser.add_argument('action', choices=actions)
        parser.add_argument('args', nargs='*')

    async def run(self):
        await actions[self.opts.action](*self.opts.args)

if __name__ == '__main__':
    Command.main()
