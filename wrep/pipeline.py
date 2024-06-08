from __future__ import annotations

import asyncio
import functools
import operator
import uuid
from collections import defaultdict
from datetime import datetime
from itertools import batched
from typing import Any, Iterable

from . import settings, utils
from . import orm
from .backends.etl import *
from .orm import *
from .models import *
from .ref import normls
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
        'industry',
        'artifacts']
    required_fields = {'company', 'reported'}
    write_fields = [
        'company',
        'location',
        'reported',
        'starting',
        'employees',
        'action',
        'url',
        'company_norm']
    json_types = {
        'id': uuid.UUID,
        'reported': datetime.fromisoformat,
        'starting': datetime.fromisoformat}

    def __init__(self, state: str, **opts) -> None:
        self.state = state.upper()
        self.scraper = scrapers[self.state]()
        self.translator = translators[self.state]()
        self.backends: dict[Stage, StageBackend] = {
            Stage.Extract: MongoExtraction(self.state),
            Stage.Translate: MongoTranslation(self.state),
            Stage.Index: MongoSearchIndex(self.state)}
        self.session: orm.Session|None = None
        self.opts = opts

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
            filters = {
                Report: [Report.state == self.state],
                Company: [self.get_companies_delete_pred()],
                Artifact: [Artifact.path.startswith(f'{self.state.lower()}/')],
                StateStat: [StateStat.id == self.state]}
            stmts = (
                orm.delete(model).where(*filters)
                for model, filters in filters.items())
            if self.session:
                for stmt in stmts:
                    self.session.execute(stmt)
            else:
                with SessionLocal() as session:
                    for stmt in stmts:
                        session.execute(stmt)
                    session.commit()
        logger.info(f'{self.state}:{stage}:clean:complete')

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
        source: ExtractionBackend = self.backends[Stage.Extract]
        prev = await backend.stat()
        if clean:
            await self.clean(stage)
        async with source.reader() as reader:
            count = await backend.run(self.translator, reader)
        cur = await backend.stat()
        nochange = cur == prev if cur else None
        return dict(count=count, prev=prev, cur=cur, nochange=nochange)

    async def load(self, clean: bool = False) -> dict:
        counts = dict.fromkeys(map(str, SaveType), 0)
        self.artifact_cache = {}
        source: TranslationBackend = self.backends[Stage.Translate]
        async with source.reader() as reader:
            with SessionLocal() as session:
                self.session = session
                if clean:
                    await self.clean(Stage.Load)
                async for entry in reader:
                    counts[self.save(entry)] += 1
                stat = session.get(StateStat, self.state)
                stat = stat or StateStat(id=self.state)
                stat.self_update(session)
                session.add(stat)
                session.commit()
            self.session = None
        del self.artifact_cache
        count = sum(counts.values())
        nochange = count == counts[SaveType.Nochange] + counts[SaveType.Skip]
        return dict(count=count, counts=counts, nochange=nochange)

    async def index(self, clean: bool = False) -> dict:
        stage = Stage.Index
        if clean:
            await self.clean(stage)
        backend: SearchIndexBackend = self.backends[stage]
        filters = dict(
            reports=[Report.state == self.state],
            companies=[self.get_companies_update_pred()],
            artifacts=[self.get_artifacts_pred()],
            states=[StateStat.id == self.state],
            naics=[])
        from .search import collections
        results: dict[str, tuple[int, int, int]] = {}
        with SessionLocal() as session:
            for name, defn in collections.items():
                it = defn.orm_model.map_reduce_exec(
                    session,
                    *filters[name],
                    lazy=bool(self.opts.get('lazy', True)))
                results[name] = await getattr(backend, f'update_{name}')(it)
        nochange = True
        counts: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = defaultdict(int)
        for name, (count, created, updated) in results.items():
            nochange &= created + updated == 0
            counts[name] = dict(count=count, created=created, updated=updated)
            totals['created'] += created
            totals['updated'] += updated
            totals['nochange'] += count - created - updated
        return dict(counts=counts, totals=dict(totals), nochange=nochange)

    STMT_REPORT_GET = (orm
        .select(Report, Artifact, Naics)
        .join(Report.artifacts, isouter=True)
        .join(Report.naics, isouter=True)
        .options(
            orm.joinedload(Report.naics),
            orm.joinedload(Report.artifacts)))

    def save(self, entry: dict) -> SaveType:
        save = SaveType.Nochange
        record = {
            field: self.from_json(field, entry[field])
            for field in self.fields if field in entry}
        if not all(map(record.get, self.required_fields)):
            return save.Skip
        uid = record.pop('id')
        stmt = self.STMT_REPORT_GET.where(Report.id == uid)
        report = self.session.scalars(stmt).unique().one_or_none()
        if report is None:
            report = Report(id=uid, state=self.state)
            save = save.Create
        naics = set(record.pop('naics', ()))
        industry = record.pop('industry', None)
        artifacts = record.pop('artifacts', {})
        self.truncate_fields(record)
        company, company_save = self.save_company(record['company'])
        record['company_norm'] = company.name_norm
        dirty = save is save.Create
        for field in self.write_fields:
            value = record.get(field)
            if dirty or getattr(report, field) != value:
                setattr(report, field, value)
                dirty = True
        if save is save.Nochange and dirty:
            save = save.Update
        if save is not save.Nochange:
            self.session.add(report)
        if save is save.Nochange and company_save is not save.Nochange:
            save = save.Update
        naics_save = self.save_naics(report, naics, industry)
        if save is save.Nochange:
            save = naics_save
        artifacts_save = self.save_artifacts(report, artifacts)
        if save is save.Nochange:
            save = artifacts_save
        return save

    def truncate_fields(self, record: dict[str, Any]) -> dict[str, int]:
        trims = {}
        for field in ('action', 'location', 'company', 'url'):
            value = record.get(field)
            limit = Report.__table__._columns[field].type.length
            if value and len(value) > limit:
                trims[field] = len(value) - limit
                record[field] = value[:limit]
        return trims

    def save_company(self, name: str) -> tuple[Company, SaveType]:
        save = SaveType.Nochange
        uid = uuid.uuid5(Company.NS, name)
        company = self.session.get(Company, uid)
        if company is None:
            company = Company(id=uid)
            save = save.Create
        record = dict(
            name=name,
            name_norm=normls.company_name_norm(name),
            name_canon=normls.company_name_canon(name))
        dirty = save is save.Create
        for field, value in record.items():
            if dirty or getattr(company, field) != value:
                setattr(company, field, value)
                dirty = True
        if save is save.Nochange and dirty:
            save = save.Update
        if save is not save.Nochange:
            self.session.add(company)
        return company, save

    def save_naics(self, report: Report, codes: set[int], industry: str|None) -> SaveType:
        save = SaveType.Nochange
        if not (codes or industry or report.naics):
            return save
        ors = [Naics.id.in_(codes)]
        if industry:
            ors += [
                Naics.title.like(industry),
                Naics.code.like(industry)]
        stmt = orm.select(Naics).where(functools.reduce(operator.or_, ors))
        current = list(self.session.execute(stmt).scalars())
        for naics in set(report.naics).difference(current):
            report.naics.remove(naics)
            save = save.Update
        for naics in set(current).difference(report.naics):
            report.naics.append(naics)
            save = save.Update
        return save

    def save_artifacts(self, report: Report, index: dict[str, str]) -> SaveType:
        save = SaveType.Nochange
        index = {
            f'{self.state.lower()}/{key}': value
            for key, value in index.items()}
        oldmap = {a.id: a for a in report.artifacts}
        artifacts: list[Artifact] = []
        for path, url in index.items():
            uid = uuid.uuid5(settings.NAMESPACE, f'artifact:{path}')
            artifact = oldmap.pop(uid, None) or self.session.get(Artifact, uid)
            if artifact is None:
                artifact = Artifact(id=uid, path=path, url=url)
                artifact.self_update()
                self.session.add(artifact)
                self.artifact_cache[uid] = None
            else:
                if path.endswith('.xlsx') and uid not in self.artifact_cache:
                    if artifact.self_update():
                        self.session.add(artifact)
                    self.artifact_cache[uid] = None
            artifacts.append(artifact)
        for artifact in set(report.artifacts).difference(artifacts):
            report.artifacts.remove(artifact)
            save = save.Update
        for artifact in set(artifacts).difference(report.artifacts):
            report.artifacts.append(artifact)
            save = save.Update
        return save

    def get_artifacts_pred(self):
        return Artifact.path.startswith(f'{self.state.lower()}/')

    def get_companies_delete_pred(self):
        return Company.id.not_in(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state != self.state))

    def get_companies_update_pred(self):
        return Company.id.in_(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state == self.state))

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
        lazy: bool|int = True,
    ):
        if clean_only and (clean or incremental):
            raise ValueError(f'Cannot specify clean_only with clean or incremental')
        self.id = uuid.uuid4()
        self.clean = clean
        self.clean_only = clean_only
        self.incremental = incremental
        self.concurrent = concurrent
        self.stages = list(utils.unique(map(Stage, stages)))
        self.states = list(utils.unique(map(str.upper, states)))
        self.pipelines = [Pipeline(state, lazy=lazy) for state in self.states]
        self.size = len(self.pipelines) * len(self.stages)
        self.runs: dict[StateCode, list[dict]] = defaultdict(list)
        self.grouping: tuple[list[Stage], ...] = [], [], []
        for stage in self.stages:
            self.grouping[self.GROUPING[stage]].append(stage)
        self.logbackend = MongoPipelineLog()
        self.info = dict(
            id=self.id,
            incremental=self.incremental,
            concurrent=self.concurrent,
            clean=self.clean or self.clean_only)

    async def run(self) -> None:
        self.start = utils.now()
        self.info.update(start=self.start)
        self.jobseq = 0
        it = iter(self.grouping)
        if self.concurrent:
            run_concurrently = self.run_concurrently
        else:
            run_concurrently = self.run_consecutively
        await run_concurrently(*next(it))
        await self.run_consecutively(*next(it))
        await run_concurrently(*next(it))

    async def run_consecutively(self, *stages: Stage) -> None:
        for pipeline in self.pipelines:
            await self.run_pipeline(pipeline, *stages)

    async def run_concurrently(self, *stages: Stage) -> None:
        for pipelines in batched(self.pipelines, 4):
            async with asyncio.TaskGroup() as group:
                for pipeline in pipelines:
                    group.create_task(self.run_pipeline(pipeline, *stages))

    async def run_pipeline(self, pipeline: Pipeline, *stages: Stage) -> None:
        for stage in stages:
            start = utils.now()
            state = pipeline.state
            res = dict(state=state, stage=stage, jobseq=self.jobseq, start=start)
            self.jobseq += 1
            res['runner'] = dict(self.info, elapsed=(start - self.start).total_seconds())
            if self._should_skip(state):
                logger.info(f'{state}:{stage}:skip')
                res.update(skip=True, nochange=True)
            elif self.clean_only:
                await pipeline.clean(stage)
                res.update(clean_only=True)
            else:
                res.update(await pipeline.run(stage, clean=self.clean))
            end = utils.now()
            res.update(end=end, elapsed=(end - start).total_seconds())
            self.runs[pipeline.state].append(res)
            await self.logbackend.save([res])

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
        parser.add_argument('--eager', '-e', dest='lazy', action='store_false')

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
