from __future__ import annotations

import glob
import hashlib
import json
from abc import abstractmethod
from contextlib import asynccontextmanager
from typing import (Any, AsyncGenerator, AsyncIterable, Callable, ClassVar,
                    Mapping)
from uuid import UUID, uuid5

import yaml
from motor.motor_asyncio import AsyncIOMotorCollection

from .. import Stage, search, settings, utils
from ..models import *
from ..utils import EitherIterable
from .mongo import (AbstractMongoCollection, ClientControlCommand, MongoClient,
                    MongoCollection, MongoQueryFilter, Search, filters)

__all__ = [
    'ExtractionBackend',
    'PipelineLogBackend',
    'SearchIndexBackend',
    'StageBackend',
    'TranslationBackend']

type Doc = dict[str, Any]
logger = utils.get_logger('backends.etl')
client = MongoClient(
    url=settings.ETL_MONGODB_URL,
    control_dbname=settings.ETL_MONGODB_CONTROL_DBNAME,
    dbname_key='etl.dbname',
    dbname_ttl=settings.ETL_MONGODB_DBNAME_TTL,
    dbname_default=settings.ETL_MONGODB_DBNAME)

collections: dict[str, MongoCollection] = dict(
    extractions=MongoCollection(
        client=client,
        name='extractions',
        indexes=[
            {'state': 1},
            {'_i': 1}]),
    translations=MongoCollection(
        client=client,
        name='translations',
        indexes=[
            {'id': 1},
            {'values_id': 1},
            {'state': 1}]),
    pipelinelogs=MongoCollection(
        client=client,
        name='pipelinelogs',
        data_model=PipelineLog,
        indexes=[
            {'stages': 1},
            {'states': 1},
            {'start': -1},
            {'end': -1},
            {'elapsed': -1}]))

class ReaderMixin:

    @abstractmethod
    @asynccontextmanager
    async def reader(self) -> AsyncGenerator[AsyncIterable[Doc]]: ...

class ContextMixin:

    def __init__(self, context: Doc|None = None) -> None:
        if context is None:
            context = {}
        self.context = context

class PipelineLogBackend(ContextMixin):
    registry: ClassVar[dict[str, type[PipelineLogBackend]]] = {}
    engine: ClassVar[str]

    @abstractmethod
    async def save(self, log: PipelineLog) -> None: ...

    @abstractmethod
    async def fetch(self, id: UUID) -> PipelineLog: ...

    @abstractmethod
    async def fetch_latest(self) -> PipelineLog: ...

    @abstractmethod
    async def findall(self, limit: Limit|None = None, offset: Offset = 0) -> AsyncIterable[PipelineLog]: ...

    @abstractmethod
    async def update(self, source: EitherIterable[PipelineLog]) -> tuple[int, int, int]: ...

    @abstractmethod
    async def prune(self, maxage: utils.Delta) -> int: ...

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine'):
            cls.registry[cls.engine] = cls

class StageBackend(ContextMixin):
    registry: ClassVar[dict[str, dict[Stage, type[StageBackend]]]] = {}
    stage: ClassVar[Stage]
    engine: ClassVar[str]

    def __init__(self, state: StateCode, context: Doc|None = None) -> None:
        super().__init__(context)
        self.state = state.upper()

    @abstractmethod
    async def clean(self) -> None: ...

    async def stat(self) -> dict:
        return {}

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if hasattr(cls, 'engine') and hasattr(cls, 'stage'):
            cls.registry.setdefault(cls.engine, {})[cls.stage] = cls

class ExtractionBackend(StageBackend, ReaderMixin):
    stage = Stage.Extract

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class TranslationBackend(StageBackend, ReaderMixin):
    stage = Stage.Translate

    @abstractmethod
    async def update(self, source: EitherIterable[Doc]) -> tuple[int, int, int]: ...

class SearchIndexBackend(StageBackend):
    stage = Stage.Index
    collections: ClassVar[Mapping[str, search.AbstractMappedCollection]]

    @abstractmethod
    async def update(self, name: str, source: EitherIterable[DataModel]) -> tuple[int, int, int]: ...

class MongoContextMixin(ContextMixin):
    engine = 'mongo'
    client: ClassVar[MongoClient]
    _db = None

    async def db(self):
        if self._db is None:
            self._db = await self.client.get_database(self.context.get(self.client.dbname_key))
            self.context[self.client.dbname_key] = self._db.name
        return self._db

class MongoContextCollectionMixin[DM: DataModel](MongoContextMixin):
    collection: ClassVar[MongoCollection]
    _coll = None
    _indexes_created = False

    @property
    def model(self) -> type[DM]|None:
        return self.collection.data_model

    @property
    def client(self) -> MongoClient:
        return self.collection.client

    async def get_collection(self):
        if self._coll is None:
            self._coll = (await self.db()).get_collection(self.collection.name)
        return self._coll

    async def create_indexes(self) -> None:
        if not self._indexes_created:
            coll = await self.get_collection()
            await coll.create_indexes(self.collection.indexes)
            self._indexes_created = True

class MongoPipelineLog(PipelineLogBackend, MongoContextCollectionMixin[PipelineLog]):
    collection = collections['pipelinelogs']

    async def save(self, log):
        doc = log.as_doc()
        await self.create_indexes()
        coll = await self.get_collection()
        res = await coll.replace_one({'_id': doc['_id']}, doc, True)

    async def fetch(self, id):
        filter: FilterModel[PipelineLog] = filters[self.model](q={'_id': id})
        db = await self.db()
        res = Search(filter, 1, dbname=db.name)
        if await res.count():
            return await anext(res.objs())
        raise ValueError(f'Not found {id=}')

    async def fetch_latest(self):
        async for log in await self.findall(limit=1):
            return log
        raise ValueError(f'No entries found')

    async def findall(self, limit: Limit|None = None, offset: Offset = 0):
        filter: FilterModel[PipelineLog] = filters[self.model]()
        db = await self.db()
        res = Search(filter, limit=limit, offset=offset, dbname=db.name)
        return res.objs()

    async def update(self, source):
        it = (x.as_doc() async for x in utils.as_aiter(source))
        await self.create_indexes()
        return await update_collection(await self.get_collection(), it)

    async def prune(self, maxage: utils.Delta) -> int:
        age = utils.deltaparse(maxage, default_unit='days')
        expiry = utils.utcnow() - age
        filt = {'start': {'$lt': expiry}}
        coll = await self.get_collection()
        res = await coll.delete_many(filt)
        return res.deleted_count

class PipelineLogFilter(FilterModel[PipelineLog], MongoQueryFilter):
    result_model: ClassVar = PipelineLog
    collection: ClassVar = MongoPipelineLog.collection
    default_ordering: ClassVar = [('start', -1)]

class MongoETBase(StageBackend, MongoContextCollectionMixin):
    'Common base class for MongoExraction & MongoTranslation'
    ordering: ClassVar[list[str]] = []
    clean_keys: ClassVar[list[str]] = []
    stat_clean_keys: ClassVar[list[str]] = []
    lookup_id_key: ClassVar[str]

    async def clean(self) -> None:
        filt = self.get_filter()
        coll = await self.get_collection()
        res = await coll.delete_many(filt)
        logger.debug(f'{filt=} {res=}')

    @asynccontextmanager
    async def reader(self):
        coll = await self.get_collection()
        it = coll.find(self.get_filter()).sort(self.ordering)
        yield utils.amap(self.clean_doc, it)

    async def stat(self):
        async with self.reader() as reader:
            it = utils.amap(self.clean_stat_doc, reader)
            return await docs_stat(it)

    def clean_doc(self, doc: Doc) -> Doc:
        for key in self.clean_keys:
            doc.pop(key, None)
        return doc

    def clean_stat_doc(self, doc: Doc) -> Doc:
        for key in self.stat_clean_keys:
            doc.pop(key, None)
        return doc

    def get_filter(self) -> Doc:
        return dict(state=self.state)

    @classmethod
    async def doc_lookup(cls, id: str|UUID, context: Doc|None = None) -> tuple[StateCode, Doc]:
        filt = {cls.lookup_id_key: UUID(str(id))}
        self = cls('XX', context=context)
        coll = await self.get_collection()
        doc = await coll.find_one(filt)
        if not doc:
            raise ValueError(f'doc {id=} not found')
        self.state = doc['state']
        return doc['state'], self.clean_doc(doc)

class MongoExtraction(MongoETBase, ExtractionBackend):
    NS: ClassVar[UUID] = uuid5(settings.NAMESPACE, 'extractions')
    collection = collections['extractions']
    ordering = ['_i']
    clean_keys = ['_id', '_i', 'state']
    stat_clean_keys = ['scrape_time', 'NAICS Codes']
    lookup_id_key = '_id'

    async def update(self, source):
        await self.clean()
        await self.create_indexes()
        coll = await self.get_collection()
        it = utils.aenumerate(source)
        it = utils.amap(self._makedoc, it)
        return await update_collection(coll, it, self.get_replace_filter)

    def get_replace_filter(self, doc: Doc) -> Doc:
        return dict(_i=doc['_i'], state=self.state)

    def _makedoc(self, item: tuple[int, Doc]) -> Doc:
        i, doc = item
        return dict(
            state=self.state,
            _i=i,
            _id=self.state_seq_docid(self.state, i)) | doc

    @classmethod
    def state_seq_docid(cls, state: StateCode, i: int) -> UUID:
        return uuid5(cls.NS, f'{state}:seq:{int(i)}')

class MongoTranslation(MongoETBase, TranslationBackend):
    collection = collections['translations']
    ordering = ['id']
    clean_keys = ['_id', 'row']
    stat_clean_keys = ['row']
    lookup_id_key = 'id'

    async def update(self, source):
        await self.create_indexes()
        coll = await self.get_collection()
        return await update_collection(coll, source, self.get_replace_filter)

    def get_replace_filter(self, entry: Doc) -> Doc:
        return {'$or': [{'id': entry['id']}, {'values_id': entry['values_id']}]}

class MongoSearchIndex(SearchIndexBackend, MongoContextMixin):
    collections: ClassVar[Mapping[str, AbstractMongoCollection]] = search.mapped_collections
    client = search.client

    async def clean(self) -> None:
        db = await self.db()
        for name, collection in self.collections.items():
            coll = db.get_collection(collection.name)
            if name == 'naics':
                coro = coll.drop()
            elif name == 'artifacts':
                coro = coll.delete_many(dict(path={'$regex': f'^{self.state.lower()}/'}))
            elif name == 'companies':
                coro = coll.delete_many({
                    '$and': [
                        {'states': self.state},
                        {'states': {'$size': 1}}]})
            elif name == 'states':
                coro = coll.delete_one(dict(id=self.state))
            else:
                coro = coll.delete_many(dict(state=self.state))
            await coro

    async def stat(self):
        collection = self.collections['reports']
        coll = (await self.db()).get_collection(collection.name)
        it = coll.find(dict(state=self.state)).sort('id')
        return await docs_stat(it)

    async def update(self, name, source):
        collection = self.collections[name]
        coll = (await self.db()).get_collection(collection.name)
        await coll.create_indexes(collection.indexes)
        it = (inst.as_doc() async for inst in utils.as_aiter(source))
        key = 'id' if name in ('states', 'naics') else '_id'
        return await update_collection(coll, it, lambda doc: {key: doc[key]})

async def update_collection(coll: AsyncIOMotorCollection, it: EitherIterable[Doc], get_filter: Callable[[Doc], Doc]|None = None) -> tuple[int, int, int]:
    count, created, updated = 0, 0, 0
    async for doc in utils.as_aiter(it):
        if get_filter:
            filt = get_filter(doc)
        else:
            filt = {'_id': doc['_id']}
        if '_id' not in filt:
            old = await coll.find_one(filt)
            if old:
                idfilt = dict(_id=old['_id'])
                filt |= idfilt
                doc = idfilt|doc
        res = await coll.replace_one(filt, doc, True)
        if res.upserted_id:
            created += 1
        elif res.modified_count:
            updated += 1
        count += 1
    return count, created, updated

async def docs_stat(it: EitherIterable[Doc]) -> Doc:
    h = hashlib.sha1()
    size, count = 0, 0
    async for doc in utils.as_aiter(it):
        buf = json.dumps(doc, default=str).encode()
        h.update(buf)
        size += len(buf)
        count += 1
    return dict(
        count=count,
        size=size,
        hash=h.hexdigest() if count else None)

class EtlCmdMixin:

    @classmethod
    def dbname_arg(cls, parser: utils.AP) -> None:
        arg = parser.add_argument
        arg('--etl-dbname', '-b',
            default=None,
            help=f'Alternate mongo etl db name')

class OneBaseCommand(utils.BaseCommand, EtlCmdMixin):

    @classmethod
    def add_arguments(cls, parser: utils.AP):
        arg = parser.add_argument
        cls.dbname_arg(parser)
        arg('--yaml', action='store_true', help='Output yaml')

    def setup(self, opts):
        self.context = {client.dbname_key: opts.etl_dbname}

    def printobj(self, obj: Any) -> None:
        print(self.objtext(obj))

    def objtext(self, obj: Any) -> str:
        obj = self.jsondoc(obj)
        if self.opts.yaml:
            text = yaml.safe_dump(obj, sort_keys=False)
        else:
            text = json.dumps(obj, indent=2)
        return text

    @staticmethod
    def jsondoc(obj: Any) -> Any:
        return json.loads(json.dumps(obj, default=str))

class TroneCommand(OneBaseCommand):
    'Run translations for a single extraction doc, and print the result'

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        arg = parser.add_argument
        arg('id', type=UUID, help='The extraction doc id')

    async def run(self):
        from ..translators import translators
        state, doc = await MongoExtraction.doc_lookup(
            self.opts.id,
            context=self.context)
        it = translators[state]().entries(doc)
        it = utils.as_aiter(it)
        res = [x async for x in it]
        self.printobj(res)

class LdoneCommand(OneBaseCommand):
    'Run load operations for a single translation doc, and print the result'

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        arg = parser.add_argument
        arg('id', type=UUID, help='The translation doc id')

    async def run(self):
        from .. import orm
        from ..pipeline import Pipeline
        state, doc = await MongoTranslation.doc_lookup(
            self.opts.id,
            context=self.context)
        pipeline = Pipeline(state, context=self.context)
        with orm.SessionLocal() as session:
            pipeline.session = session
            pipeline.artifact_cache = {}
            report, save = pipeline.save(doc)
            if report is not None:
                report, = orm.Report.map_reduce([(report, report, None, None)])
                report = report.model_dump(mode='json')
            session.rollback()
        self.printobj(dict(save=save, report=report))

class LogCmdMixin(EtlCmdMixin):

    def get_backend(self, dbname: str|None) -> MongoPipelineLog:
        return MongoPipelineLog(context={client.dbname_key: dbname})

class LogShowCommand(utils.BaseCommand, LogCmdMixin):
    'Show pipeline log'
    summary_methods: ClassVar[dict[str, str]] = {
        'short': 'get_short',
        'runs': 'get_runs',
        'load-changes': 'get_load_changes',
        'scrape-stats': 'get_scrape_stats'}
    summary_fields: ClassVar[dict[str, tuple[str, ...]|dict[str, Any]]] = {
        'short': dict(key=0, value=1),
        'runs': ('stage', 'state', 'elapsed', 'failed', 'nochange'),
        'load-changes': ('state', 'created', 'updated'),
        'scrape-stats': ('state', 'elapsed')}

    @classmethod
    def add_arguments(cls, parser):
        super().add_arguments(parser)
        arg = parser.add_argument
        arg(
            '--summary', '-s',
            choices=cls.summary_methods,
            default=None,
            help=(f'The summary type to show'))
        arg(
            '--output', '-o',
            choices=['json', 'yaml', 'table'],
            help=f'Output format')
        arg(
            '--tablefmt',
            default='simple',
            help=f'Table format')
        cls.dbname_arg(parser)
        arg(
            'id',
            type=UUID,
            nargs='?',
            default=None,
            help='The pipeline log ID, default latest')

    def setup(self, opts):
        self.summary: str|None = self.opts.summary
        self.output: str = self.opts.output
        if not self.summary and self.output == 'table':
            self.parser.error(f'Table output only supported with summary')
        self.backend = self.get_backend(opts.etl_dbname)

    async def run(self):
        if self.opts.id:
            log = await self.backend.fetch(self.opts.id)
        else:
            log = await self.backend.fetch_latest()
        if self.summary:
            body = getattr(log, self.summary_methods[self.summary])()
        else:
            body = log.model_dump(mode='json')
            body['runs'] = len(body['runs'])
            body['states'] = len(body['states'])
        if self.output == 'table':
            head = self.summary_fields[self.summary]
            if not isinstance(head, Mapping):
                head = dict(zip(head, head))
            if isinstance(body, Mapping):
                body = list(body.items())
            from tabulate import tabulate
            text = tabulate(body, head, tablefmt=self.opts.tablefmt, floatfmt='.2f')
        elif self.output == 'yaml':
            text = yaml.safe_dump(body, sort_keys=False)
        else:
            text = json.dumps(body, indent=2)
        print(text)

class LogCopyCommand(utils.BaseCommand, LogCmdMixin):
    'Copy pipeline logs to another db'

    @classmethod
    def add_arguments(cls, parser):
        cls.dbname_arg(parser)
        parser.add_argument('dest', help='The destination db name')

    def setup(self, opts):
        self.src = self.get_backend(opts.etl_dbname)
        self.dst = self.get_backend(opts.dest)

    async def run(self):
        src_db = await self.src.db()
        dst_db = await self.dst.db()
        if src_db.name == dst_db.name:
            raise ValueError(f'Source and dest db cannot be the same')
        logger.info(f'Copying from {src_db.name} to {dst_db.name}')
        res = await self.dst.update(await self.src.findall())
        counts = dict(zip(('count', 'created', 'updated'), res))
        print(counts)

class LogPruneCommand(utils.BaseCommand, LogCmdMixin):
    'Prune old pipeline logs'

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            '--maxage', '-m',
            type=utils.deltaopt('days'),
            default='30d',
            help='Max age, default 30d')
        cls.dbname_arg(parser)

    def setup(self, opts):
        self.backend = self.get_backend(opts.etl_dbname)

    async def run(self):
        res = await self.backend.prune(self.opts.maxage)
        counts = dict(deleted=res)
        print(counts)

class LogCommand(utils.BaseCommand):
    'Pipeline log commands'
    commands = dict(
        show=LogShowCommand,
        copy=LogCopyCommand,
        prune=LogPruneCommand)

class ArtifactsBaseCommand(utils.BaseCommand):

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg(
            '--check-only', '-c',
            action='store_false',
            dest='change',
            help='Check only, do not make changes')

    def setup(self, opts):
        super().setup(opts)
        self.root = settings.ARTIFACTS_DIR

class ArtifactsPruneCommand(ArtifactsBaseCommand):
    'Delete orphan artifacts from file system'

    async def run(self):
        from .. import orm
        it = glob.iglob('**/*.*', root_dir=self.root, recursive=True)
        with orm.SessionLocal() as session:
            for path in it:
                file = self.root/path
                if path.endswith('.sha1'):
                    logger.info(f'Cruft {path=}')
                    if self.opts.change:
                        file.unlink()
                    continue
                id = orm.Artifact.path_to_id(path)
                try:
                    session.get(orm.Artifact, id)
                except orm.NoResultFound:
                    logger.info(f'Orphan {path=} {id=}')
                    if self.opts.change:
                        file.unlink()
                        utils.digestfile(file).unlink(missing_ok=True)
                else:
                    logger.debug(f'Found {path=} {id=}')

class ArtifactsCheckCommand(ArtifactsBaseCommand):
    'Check for missing artifact files'

    async def run(self):
        from .. import orm
        stmt = orm.select(orm.Artifact)
        with orm.SessionLocal() as session:
            for art in session.scalars(stmt):
                file = self.root/art.path
                if file.exists():
                    logger.debug(f'Found path={art.path} id={art.id}')
                    if art.self_update():
                        logger.info(f'Updated path={art.path} id={art.id}')
                        session.add(art)
                else:
                    logger.warning(f'Missing path={art.path} id={art.id}')
            if self.opts.change:
                session.commit()
            else:
                session.rollback()


class ArtifactsCommand(utils.BaseCommand):
    'Artifacts maintenance'
    commands = dict(
        check=ArtifactsCheckCommand,
        prune=ArtifactsPruneCommand)

class Command(utils.BaseCommand):
    'Misc ETL pipeline commands'
    commands = dict(
        log=LogCommand,
        artifacts=ArtifactsCommand,
        trone=TroneCommand,
        ldone=LdoneCommand,
        control=ClientControlCommand(client))
