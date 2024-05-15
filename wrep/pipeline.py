from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime
from itertools import batched
from typing import Any, Iterable


from . import utils
from .backends.etl import *
from .models import *
from .models import db
from .scrapers import scrapers
from .search import mongo
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
        self.backends: dict[Stage, StageBackend] = {
            stage: cls(self.state, mongo)
            for stage, cls in dict.items({
                Stage.Extract: MongoExtraction,
                Stage.Translate: MongoTranslation,
                Stage.Index: MongoSearchIndex})}

    async def run(self, stage: Stage, clean: bool = False) -> dict:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:start')
        summary: dict = await getattr(self, stage)(clean=clean)
        logger.info(f'{self.state}:{stage}:complete {summary}')
        return summary

    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:clean')
        if stage in self.backends:
            await self.backends[stage].clean()
        elif stage is stage.Scrape:
            await self.scraper.clean()
        elif stage is stage.Load:
            for model in Report, Company:
                model.delete().where(model.state == self.state).execute()
            StateStat.delete().where(StateStat.id == self.state).execute()

    async def scrape(self, clean: bool = False) -> dict:
        prev = await self.scraper.stat()
        if clean:
            await self.clean(Stage.Scrape)
        await self.scraper.scrape()
        cur = await self.scraper.stat()
        nochange = cur == prev if cur else None
        return dict(prev=prev, cur=cur, nochange=nochange)

    async def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        backend: ExtractionBackend = self.backends[stage]
        prev = await backend.stat()
        logger.info(f'{self.state}:{stage}:stat {prev}')
        if clean:
            await self.clean(stage)
        with self.scraper.extract() as source:
            count = await backend.update(source)
        cur = await backend.stat()
        nochange = cur == prev if cur else None
        return dict(count=count, prev=prev, cur=cur, nochange=nochange)

    async def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        backend: TranslationBackend = self.backends[stage]
        source = self.backends[Stage.Extract]
        prev = await backend.stat()
        if clean:
            await self.clean(Stage.Translate)
        async with source.reader() as reader:
            count = await backend.run(self.translator, reader)
        cur = await backend.stat()
        nochange = cur == prev if cur else None
        return dict(count=count, prev=prev, cur=cur, nochange=nochange)

    async def load(self, clean: bool = False) -> dict:
        counts = dict.fromkeys(map(str, SaveType), 0)
        async with self.backends[Stage.Translate].reader() as reader:
            with db.atomic():
                if clean:
                    await self.clean(Stage.Load)
                async for entry in reader:
                    counts[self.save(entry)] += 1
                stat = StateStat.get_or_create(id=self.state)[0]
                stat.self_update()
                stat.save()
        count = sum(counts.values())
        nochange = count == counts[SaveType.Nochange] + counts[SaveType.Skip]
        return dict(count=count, counts=counts, nochange=nochange)

    async def index(self, clean: bool = False) -> dict:
        stage = Stage.Index
        if clean:
            await self.clean(stage)
        backend: IndexBackend = self.backends[stage]
        q = Report.select_for_reduce().where(Report.state == self.state)
        reports = ReportData.map_reduce(q)
        count, created, updated = await backend.update_reports(reports)
        nochange = created + updated == 0
        counts = dict(created=created, updated=updated)
        q = StateStat.select().where(StateStat.id == self.state)
        detail = StateDetail.model_validate(q.get())
        await backend.update_states(detail)
        q = Company.select_for_reduce().where(Report.state == self.state)
        await backend.update_companies(CompanyDetail.map_reduce(q))
        await backend.update_naics(NaicsDetail.map_reduce())
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
        self.truncate_fields(record)
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
        Company.get_or_create(company=report.company, state=report.state)
        return save

    def truncate_fields(self, record: dict[str, Any]) -> dict[str, int]:
        trims = {}
        for field in ('action', 'location', 'company'):
            value = record.get(field)
            limit = getattr(Report, field).max_length
            if value and len(value) > limit:
                trims[field] = len(value) - limit
                record[field] = value[:limit]
        return trims

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

    def from_json(self, field: str, value: Any) -> Any:
        if field in self.json_types:
            if isinstance(value, str):
                value = self.json_types[field](value)
        return value

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
        concurrent: bool = False,
    ):
        if clean_only and (clean or incremental):
            raise ValueError(f'Cannot specify clean_only with clean or incremental')
        self.clean = clean
        self.clean_only = clean_only
        self.incremental = incremental
        self.concurrent = concurrent
        self.stages = list(utils.unique(map(Stage, stages)))
        self.states = list(utils.unique(map(str.upper, states)))
        self.pipelines = list(map(Pipeline, self.states))
        self.runs: dict[StateCode, list[dict]] = defaultdict(list)
        self.grouping: tuple[list[Stage], ...] = [], [], []
        for stage in self.stages:
            self.grouping[self.GROUPING[stage]].append(stage)

    async def run(self) -> None:
        it = iter(self.grouping)
        if self.concurrent:
            run_concurrently = self._run_concurrently
        else:
            run_concurrently = self._run_consecutively
        await run_concurrently(*next(it))
        await self._run_consecutively(*next(it))
        await run_concurrently(*next(it))

    async def _run_consecutively(self, *stages: Stage) -> None:
        for pipeline in self.pipelines:
            await self._run_pipeline(pipeline, *stages)

    async def _run_concurrently(self, *stages: Stage) -> None:
        for pipelines in batched(self.pipelines, 4):
            async with asyncio.TaskGroup() as group:
                for pipeline in pipelines:
                    group.create_task(self._run_pipeline(pipeline, *stages))

    async def _run_pipeline(self, pipeline: Pipeline, *stages: Stage) -> None:
        for stage in stages:
            state = pipeline.state
            res = dict(state=state, stage=stage)
            if self._should_skip(state):
                logger.info(f'{state}:{stage}:skip')
                res.update(skip=True, nochange=True)
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
        parser.add_argument('--concurrent', '-t', action='store_true')

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
