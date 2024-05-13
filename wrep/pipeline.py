from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from . import search, settings, utils
from .backends.etl import *
from .models import *
from .models import db
from .scrapers import scrapers
from .translators import translators
from .utils import ConfigError

logger = utils.get_logger('pipeline')

class Stage(utils.StrEnum):
    Scrape = 'scrape'
    Extract = 'extract'
    Translate = 'translate'
    Load = 'load'
    Index = 'index'

class SaveType(utils.StrEnum):
    Create = 'create'
    Update = 'update'
    Nochange = 'nochange'
    Skip = 'skip'

class Pipeline:

    fields = [
        'id',
        'company',
        'location',
        'reported',
        'starting',
        'employees',
        'action',
        'url',
        'naics',
        'industry']
    required_fields = {'company', 'reported'}
    json_types = {
        'id': uuid.UUID,
        'reported': datetime.fromisoformat,
        'starting': datetime.fromisoformat}

    def __init__(self, state: str) -> None:
        self.state = state.upper()
        self.scraper = scrapers[self.state]()
        self.translator = translators[self.state]()
        self.namespace = uuid.uuid5(Report.NAMESPACE, self.state)
        self.is_mongo = settings.MONGODB_ENABLED
        self.mongo = search.mongo if self.is_mongo else None
        self.extraction_backend = self._extraction_backend()
        self.translation_backend = self._translation_backend()
        self.summary = {}

    async def run(self, stage: Stage, clean: bool = False) -> None:
        stage = Stage(stage)
        logger.info(f'run {stage} {self.state}')
        self.summary[stage] = await getattr(self, stage)(clean=clean)
        logger.info(f'run {stage} {self.state} {self.summary[stage]}')

    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'clean {stage} {self.state}')
        if stage is stage.Scrape:
            await self.scraper.clean()
        elif stage is stage.Extract:
            await self.extraction_backend.clean()
        elif stage is stage.Translate:
            await self.translation_backend.clean()
        elif stage is stage.Load:
            Report.delete().where(Report.state == self.state).execute()
        elif stage is stage.Index:
            if not self.is_mongo:
                raise ConfigError(f'mongo not enabled')
            await self.mongo.reports.delete_many(dict(state=self.state))

    async def scrape(self, clean: bool = False) -> dict:
        prev = self.scraper.stat()
        if clean:
            await self.clean(Stage.Scrape)
        await self.scraper.scrape()
        cur = self.scraper.stat()
        return dict(prev=prev, cur=cur)

    async def extract(self, clean: bool = False) -> dict:
        if clean:
            await self.clean(Stage.Extract)
        count = await self.extraction_backend.run()
        return dict(stats=self.scraper.stat(), count=count)

    async def translate(self, clean: bool = False) -> dict:
        if clean:
            await self.clean(Stage.Translate)
        async with self.translation_backend.runctx() as (reader, writer):
            count = 0
            async for row in reader:
                count += 1
                entry = self.translator.entry(row)
                entry.update(id=self.entry_uuid(entry, row), state=self.state, row=row)
                await writer.write(entry)
        return dict(count=count)

    async def load(self, clean: bool = False) -> dict:
        counts = dict.fromkeys(map(str, SaveType), 0)
        async with self.translation_backend.reader() as reader:
            with db.atomic():
                if clean:
                    await self.clean(Stage.Load)
                async for entry in reader:
                    counts[self.save(entry)] += 1
        counts['total'] = sum(counts.values())
        return counts

    async def index(self, clean: bool = False) -> dict:
        if self.mongo is None:
            raise ConfigError(f'mongo not enabled')
        if clean:
            await self.clean(Stage.Index)
        q = Report.select_for_reduce()
        q = q.where(Report.state == self.state)
        docs = map(ReportData.as_doc, ReportData.map_reduce(q))
        count = q.count()
        counts = dict(created=0, updated=0)
        if clean:
            if count:
                await self.mongo.reports.insert_many(docs, ordered=False)
                counts['created'] += count
        else:
            for doc in docs:
                filt = dict(_id=doc['_id'])
                res = await self.mongo.reports.replace_one(filt, doc, True)
                counts['updated'] += res.modified_count
        return counts

    def save(self, entry: dict) -> SaveType:
        save = SaveType.Nochange
        record = {
            field: self.from_json(field, entry[field])
            for field in self.fields if field in entry}
        if not all(map(record.get, self.required_fields)):
            return save.Skip
        uid = record.pop('id')
        try:
            report = Report.get_by_id(uid)
        except Report.DoesNotExist:
            report = Report(id=uid, state=self.state)
            save = save.Create
        naics = set(record.pop('naics', ()))
        industry = record.pop('industry', None)
        for field, value in record.items():
            if save is save.Create or getattr(report, field) != value:
                setattr(report, field, value)
        if save is save.Nochange and report.dirty_fields:
            save = save.Update
        if save is not save.Nochange:
            report.save(force_insert=save is save.Create)
        naics_save = self.save_naics(report, naics, industry)
        if save is save.Nochange:
            save = naics_save
        return save

    def save_naics(self, report: Report, codes: set[int], industry: str|None) -> SaveType:
        save = SaveType.Nochange
        if industry:
            q = Naics.select(Naics.id)
            q = q.where(Naics.title.like(industry) | Naics.code.like(industry))
            codes.update(n.id for n in q)
        q = NaicsReport.delete()
        q = q.where(
            NaicsReport.report == report,
            NaicsReport.naics.not_in(codes))
        if q.execute():
            save = save.Update
        q = NaicsReport.select(NaicsReport.naics)
        q = q.where(NaicsReport.report == report)
        cur = [nr.naics for nr in q]
        q = Naics.select(Naics.id)
        q = q.where(
            Naics.id.in_(codes),
            Naics.id.not_in(cur))
        add = [dict(naics=naics, report=report) for naics in q]
        if add:
            save = save.Update
            NaicsReport.insert_many(add).execute()
        return save

    def entry_uuid(self, entry: dict[str, Any], row: dict[str, str]) -> uuid.UUID:
        src = entry.get('report_id') or json.dumps(list(row.values()))
        return uuid.uuid5(self.namespace, src)

    def from_json(self, field: str, value: Any) -> Any:
        if field in self.json_types:
            if isinstance(value, str):
                value = self.json_types[field](value)
        return value

    def _extraction_backend(self) -> ExtractionBackend:
        if self.is_mongo:
            cls = MongoExtraction
            dest = self.mongo.extractions
        else:
            cls = FileExtraction
            dest = settings.BUILD_DIR/'extract'/f'{self.state.lower()}.log'
        return cls(self.scraper, dest)

    def _translation_backend(self) -> TranslationBackend:
        if self.is_mongo:
            cls = MongoTranslation
            dest = self.mongo.translations
        else:
            cls = FileTranslation
            dest = settings.BUILD_DIR/'translate'/f'{self.state.lower()}.log'
        return cls(self.extraction_backend, dest)

class Command(utils.BaseCommand):
    'Run a pipeline stage'

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('stage', metavar='stages')
        parser.add_argument('states', nargs='*', metavar='state')
        parser.add_argument('--clean', '-c', action='store_true')
        parser.add_argument('--clean-only', '-x', action='store_true')

    def setup(self, opts):
        self.stages = list(utils.unique(map(self.get_stage, opts.stage.split(','))))
        self.states = list(utils.unique(map(str.upper, opts.states or translators)))
        self.pipelines = list(map(Pipeline, self.states))
        self.stages_groups = [], [], []
        groupings = [
            [Stage.Scrape, Stage.Extract, Stage.Translate],
            [Stage.Load],
            [Stage.Index]]
        for stage in self.stages:
            for i, grouping in enumerate(groupings):
                if stage in grouping:
                    break
            else:
                raise ValueError(stage)
            self.stages_groups[i].append(stage)

    async def run(self):
        it = iter(self.stages_groups)
        await self.run_concurrently(*next(it))
        await self.run_consecutively(*next(it))
        await self.run_concurrently(*next(it))

    async def run_consecutively(self, *stages: Stage):
        for pipeline in self.pipelines:
            await self.run_pipeline(pipeline, *stages)

    async def run_concurrently(self, *stages: Stage):
        async with asyncio.TaskGroup() as tg:
            for pipeline in self.pipelines:
                tg.create_task(self.run_pipeline(pipeline, *stages))

    async def run_pipeline(self, pipeline: Pipeline, *stages: Stage):
        for stage in stages:
            if self.opts.clean_only:
                coro = pipeline.clean(stage)
            else:
                coro = pipeline.run(stage, clean=self.opts.clean)
            await coro

    @staticmethod
    def get_stage(value: Stage|str) -> Stage:
        if len(value) == 1:
            for stage in Stage:
                if stage[0] == value.lower():
                    return stage
        return Stage(value.lower())

if __name__ == '__main__':
    Command.main()
