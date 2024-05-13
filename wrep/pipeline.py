from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable

from . import search, settings, utils
from .backends.etl import *
from .models import *
from .models import db
from .scrapers import scrapers
from .translators import translators

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

    async def run(self, stage: Stage, clean: bool = False) -> dict:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:start')
        summary: dict = await getattr(self, stage)(clean=clean)
        logger.info(f'{self.state}:{stage}:complete {summary}')
        return summary

    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:clean')
        if stage is stage.Scrape:
            await self.scraper.clean()
        elif stage is stage.Extract:
            await self.extraction_backend.clean()
        elif stage is stage.Translate:
            await self.translation_backend.clean()
        elif stage is stage.Load:
            Report.delete().where(Report.state == self.state).execute()
        elif stage is stage.Index:
            if self.is_mongo:
                await self.mongo.reports.delete_many(dict(state=self.state))

    async def scrape(self, clean: bool = False) -> dict:
        prev = await self.scraper.stat()
        if clean:
            await self.clean(Stage.Scrape)
        await self.scraper.scrape()
        cur = await self.scraper.stat()
        nochange = cur == prev if cur else None
        return dict(prev=prev, cur=cur, nochange=nochange)

    async def extract(self, clean: bool = False) -> dict:
        prev = await self.extraction_backend.stat()
        if clean:
            await self.clean(Stage.Extract)
        count = await self.extraction_backend.run()
        cur = await self.extraction_backend.stat()
        nochange = cur == prev if cur else None
        return dict(count=count, prev=prev, cur=cur, nochange=nochange)

    async def translate(self, clean: bool = False) -> dict:
        prev = await self.translation_backend.stat()
        if clean:
            await self.clean(Stage.Translate)
        async with self.translation_backend.runctx() as (reader, writer):
            count = 0
            async for row in reader:
                count += 1
                entry = self.translator.entry(row)
                entry.update(id=self.entry_uuid(entry, row), state=self.state, row=row)
                await writer.write(entry)
        cur = await self.translation_backend.stat()
        nochange = cur == prev if cur else None
        return dict(count=count, prev=prev, cur=cur, nochange=nochange)

    async def load(self, clean: bool = False) -> dict:
        counts = dict.fromkeys(map(str, SaveType), 0)
        async with self.translation_backend.reader() as reader:
            with db.atomic():
                if clean:
                    await self.clean(Stage.Load)
                async for entry in reader:
                    counts[self.save(entry)] += 1
        count = sum(counts.values())
        nochange = count == counts[SaveType.Nochange] + counts[SaveType.Skip]
        return dict(count=count, counts=counts, nochange=nochange)

    async def index(self, clean: bool = False) -> dict:
        if not self.is_mongo:
            logger.warning('mongo not enabled, nothing to do.')
            return dict(skip=True)
        if clean:
            await self.clean(Stage.Index)
        counts = dict.fromkeys(map(str, SaveType), 0)
        q = Report.select_for_reduce()
        q = q.where(Report.state == self.state)
        docs = map(ReportData.as_doc, ReportData.map_reduce(q))
        it = utils.CountingIter(docs)
        for doc in it:
            filt = dict(_id=doc['_id'])
            res = await self.mongo.reports.replace_one(filt, doc, True)
            if res.upserted_id:
                counts[SaveType.Create] += 1
            elif res.modified_count:
                counts[SaveType.Update] += 1
            else:
                counts[SaveType.Nochange] += 1
        count = sum(counts.values())
        nochange = count == counts[SaveType.Nochange]
        return dict(count=count, counts=counts, nochange=nochange)

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

class PipelineRunner:

    GROUPING = {
        Stage.Scrape: 0,
        Stage.Extract: 0,
        Stage.Translate: 0,
        Stage.Load: 1,
        Stage.Index: 2}

    def __init__(
        self,
        stages: Iterable[Stage|str],
        states: Iterable[StateCode],
        clean: bool = False,
        clean_only: bool = False,
        incremental: bool = False,
    ):
        if clean_only and (clean or incremental):
            raise ValueError(f'Cannot specify clean_only with clean or incremental')
        self.clean = clean
        self.clean_only = clean_only
        self.incremental = incremental
        self.stages = list(utils.unique(map(Stage, stages)))
        self.states = list(utils.unique(map(str.upper, states)))
        self.pipelines = list(map(Pipeline, self.states))
        self.runs: dict[StateCode, list[dict]] = defaultdict(list)
        self.grouping: tuple[list[Stage], ...] = [], [], []
        for stage in self.stages:
            self.grouping[self.GROUPING[stage]].append(stage)

    async def run(self) -> None:
        it = iter(self.grouping)
        await self._run_concurrently(*next(it))
        await self._run_consecutively(*next(it))
        await self._run_concurrently(*next(it))

    async def _run_consecutively(self, *stages: Stage) -> None:
        for pipeline in self.pipelines:
            await self._run_pipeline(pipeline, *stages)

    async def _run_concurrently(self, *stages: Stage) -> None:
        async with asyncio.TaskGroup() as group:
            for pipeline in self.pipelines:
                group.create_task(self._run_pipeline(pipeline, *stages))

    async def _run_pipeline(self, pipeline: Pipeline, *stages: Stage) -> None:
        for stage in stages:
            state = pipeline.state
            res = dict(state=state, stage=stage)
            if self._should_skip(state):
                logger.info(f'{state}:{stage}:skip')
                res.update(skip=True)
            elif self.clean_only:
                await pipeline.clean(stage)
                res.update(clean_only=True)
            else:
                res = await pipeline.run(stage, clean=self.clean)
                res.update(clean=self.clean)
            self.runs[pipeline.state].append(res)

    def _should_skip(self, state: StateCode) -> bool:
        return bool(
            self.incremental and
            (runs := self.runs[state]) and
            runs[-1].get('nochange'))

class Command(utils.BaseCommand):
    'Run a pipeline'

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('stages', metavar='stages', type=cls.stages_opt)
        parser.add_argument('states', nargs='*', metavar='state')
        parser.add_argument('--clean', '-c', action='store_true')
        parser.add_argument('--clean-only', '-x', action='store_true')
        parser.add_argument('--incremental', '-i', action='store_true')

    def setup(self, opts):
        opts.states = opts.states or list(translators)
        self.runner = PipelineRunner(**vars(opts))

    async def run(self):
        await self.runner.run()

    @staticmethod
    def stages_opt(value: str) -> list[Stage]:
        if value == 'all':
            return list(Stage)
        values = map(str.lower, value.split(','))
        stages = []
        for value in values:
            if len(value) == 1:
                for stage in Stage:
                    if stage[0] == value:
                        stages.append(stage)
                        break
                else:
                    stages.append(Stage(value))
            else:
                stages.append(Stage(value))
        return stages

if __name__ == '__main__':
    Command.main()
