from __future__ import annotations

import asyncio
import functools
import operator
import uuid
from collections import defaultdict, deque
from itertools import chain
from pathlib import Path
from threading import Thread
from types import MappingProxyType as MapProxy
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from sentry_sdk import capture_exception

from . import SaveType, Stage, orm, utils
from .backends.etl import *
from .models import *
from .orm import *
from .ref import normls

if TYPE_CHECKING:
    from .scrapers import Scraper
    from .translators import Translator

logger = utils.get_logger('pipeline')

class Pipeline:
    required_fields: ClassVar[tuple[str, ...]] = (
        'company',
        'reported')
    write_fields: ClassVar[tuple[str, ...]] = (
        'company',
        'location',
        'reported',
        'starting',
        'employees',
        'action',
        'url',
        'company_norm_id')
    BACKENDS: ClassVar[Mapping[Stage, type[StageBackend]]] = MapProxy(
        StageBackend.registry['mongo'])

    def __init__(self, state: StateCode, context: dict[str, Any]|None = None, opts: PipelineOpts|dict|None = None) -> None:
        if context is None:
            context = {}
        self.state = state.upper()
        self.context = context
        self.backends: dict[Stage, StageBackend] = {}
        self.opts = PipelineOpts.model_validate(opts or {})
        self.session: orm.Session|None = None

    @utils.lazyprop
    def scraper(self) -> Scraper:
        from .scrapers import scrapers
        return scrapers[self.state](opts=self.opts)

    @utils.lazyprop
    def translator(self) -> Translator:
        from .translators import translators
        return translators[self.state]()

    def backend[B: StageBackend](self, stage: Stage|type[B]) -> StageBackend|B:
        if isinstance(stage, type):
            stage = stage.stage
        try:
            backend = self.backends[stage]
        except KeyError:
            backend = self.BACKENDS[stage](
                self.state,
                context=self.context)
            self.backends[stage] = backend
        return backend

    async def run(self, stage: Stage, clean: bool = False) -> dict:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:start')
        summary: dict = await getattr(self, stage)(clean=clean)
        logger.info(f'{self.state}:{stage}:complete {summary}')
        return summary

    async def stat(self, stage: Stage) -> dict:
        stage = Stage(stage)
        if stage in self.BACKENDS:
            return await self.backend(stage).stat()
        if stage is stage.Scrape:
            return await self.scraper.stat()
        if stage is stage.Load:
            stat: dict[str, int] = {}
            backend = self.backend(SearchIndexBackend)
            filters = self.get_orm_select_filters()
            with ensure_session(self.session) as session:
                for name, defn in backend.collections.items():
                    if name in ('naics', 'states'):
                        continue
                    it = defn.orm_model.map_reduce_exec(
                        session,
                        *filters[defn.orm_model],
                        lazy=bool(self.opts.lazy))
                    stat[name] = sum(1 for _ in it)
            return stat
        raise ValueError(stage)
        
    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'{self.state}:{stage}:clean')
        if stage in self.BACKENDS:
            await self.backend(stage).clean()
            if stage is stage.Extract:
                await self.scraper.extract_clean()
        elif stage is stage.Scrape:
            await self.scraper.clean()
        elif stage is stage.Load:
            filters = self.get_orm_clean_filters()
            stmts = (
                orm.delete(model).where(*filters)
                for model, filters in filters.items())
            with ensure_session(self.session) as session:
                for stmt in stmts:
                    session.execute(stmt)
                if not self.session:
                    session.commit()
        logger.info(f'{self.state}:{stage}:clean:complete')

    async def scrape(self, clean: bool = False) -> dict:
        stage = Stage.Scrape
        prev = await self.stat(stage)
        logger.info(f'{self.state}:{stage}:stat {prev}')
        if clean:
            await self.clean(stage)
        self.scraper.metrics.clear()
        self.scraper.artifacts.metrics.clear()
        await self.scraper.scrape()
        metrics = dict(self.scraper.metrics)
        if self.scraper.artifacts.metrics:
            metrics.update(artifacts=dict(self.scraper.artifacts.metrics))
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        res = dict(nochange=nochange, prev=prev, cur=cur)
        if metrics:
            res.update(metrics=metrics)
        return res

    async def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        backend = self.backend(ExtractionBackend)
        prev = await self.stat(stage)
        logger.info(f'{self.state}:{stage}:stat {prev}')
        if clean:
            await self.clean(stage)
        async with utils.awith(self.scraper.extract()) as source:
            count = (await backend.update(source))[0]
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        return dict(nochange=nochange, count=count, prev=prev, cur=cur)

    async def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        backend = self.backend(TranslationBackend)
        source = self.backend(ExtractionBackend)
        prev = await self.stat(stage)
        logger.info(f'{self.state}:{stage}:stat {prev}')
        if clean:
            await self.clean(stage)
        async with source.reader() as reader:
            with SessionLocal() as session:
                self.translator.session = session
                it = (x.model_dump(mode='json') async for x in reader)
                it = utils.amap(self.translator.entries, it)
                it = utils.achain_from_iterable(it)
                count, created, updated = await backend.update(it)
            self.translator.session = None
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        counts = dict(count=count, created=created, updated=updated)
        return dict(nochange=nochange) | counts | dict(prev=prev, cur=cur)

    async def load(self, clean: bool = False) -> dict:
        counts = dict.fromkeys(map(str, SaveType), 0)
        self.artifact_cache = {}
        source = self.backend(TranslationBackend)
        async with source.reader() as reader:
            with SessionLocal() as session:
                self.session = session
                if clean:
                    await self.clean(Stage.Load)
                async for translation in reader:
                    counts[self.save(translation)[1]] += 1
                stat = session.get(StateStat, self.state)
                stat = stat or StateStat(id=self.state)
                stat.self_update(session)
                session.add(stat)
                session.commit()
            self.session = None
        del self.artifact_cache
        count = sum(counts.values())
        nochange = count == counts[SaveType.Nochange] + counts[SaveType.Skip]
        return dict(nochange=nochange, count=count, counts=counts)

    async def index(self, clean: bool = False) -> dict:
        stage = Stage.Index
        if clean:
            await self.clean(stage)
        backend = self.backend(SearchIndexBackend)
        filters = self.get_orm_select_filters()
        results: dict[str, tuple[int, int, int]] = {}
        with SessionLocal() as session:
            for name, defn in backend.collections.items():
                it = defn.orm_model.map_reduce_exec(
                    session,
                    *filters[defn.orm_model],
                    lazy=bool(self.opts.lazy))
                results[name] = await backend.update(name, it)
        nochange = True
        counts: dict[str, dict[str, int]] = {}
        totals: dict[str, int] = defaultdict(int)
        for name, (count, created, updated) in results.items():
            nochange &= created + updated == 0
            counts[name] = dict(count=count, created=created, updated=updated)
            totals['created'] += created
            totals['updated'] += updated
            totals['nochange'] += count - created - updated
        return dict(nochange=nochange, counts=counts, totals=dict(totals))

    def save(self, translation: Translation) -> tuple[Report|None, SaveType]:
        save = SaveType.Nochange
        record = translation.model_dump(exclude_unset=True)
        if not all(map(record.get, self.required_fields)):
            return None, save.Skip
        uid = record.pop('id')
        stmt = orm.STMT_REPORT_GET.where(Report.id == uid)
        report = self.session.scalars(stmt).unique().one_or_none()
        if report is None:
            report = Report(id=uid, state=self.state)
            save = save.Create
        naics = set(record.pop('naics', ()))
        industry = record.pop('industry', None)
        artifacts = record.pop('artifacts', {})
        self.truncate_fields(record)
        company, company_save = self.save_company(record['company'])
        record.update(company_norm_id=company.name_norm_id)
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
        naics_save = self.save_naics(report, naics, industry)
        artifacts_save = self.save_artifacts(report, artifacts)
        if save is save.Nochange:
            if naics_save is not save.Nochange or artifacts_save is not save.Nochange:
                save = save.Update
                self.session.add(report)
            elif company_save is not save.Nochange:
                save = save.Update
        return report, save

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
        record['name_norm_id'] = uuid.uuid5(Company.NS, record['name_norm'])
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
        stmt = orm.lazify(stmt, lazy=False, joins=[Naics.ancs])
        current = set(self.session.execute(stmt).unique().scalars())
        current.update(chain.from_iterable(x.ancs for x in tuple(current)))
        for naics in set(report.naics).difference(current):
            report.naics.remove(naics)
            save = save.Update
        for naics in current.difference(report.naics):
            report.naics.append(naics)
            save = save.Update
        return save

    def save_artifacts(self, report: Report, index: dict[str, str]) -> SaveType:
        save = SaveType.Nochange
        index = {
            str(Path(f'{self.state.lower()}/{key}')): value
            for key, value in index.items()}
        oldmap = {a.id: a for a in report.artifacts}
        artifacts: list[Artifact] = []
        for path, url in index.items():
            uid = Artifact.path_to_id(path)
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

    def get_orm_clean_filters(self) -> dict[type[orm.MapReduceBase], list[orm.BinaryExpression]]:
        return {
            Report: [Report.state == self.state],
            Company: [self.get_companies_delete_pred()],
            Artifact: [self.get_artifacts_pred()],
            StateStat: [StateStat.id == self.state]}

    def get_orm_select_filters(self) -> dict[type[orm.MapReduceBase], list[orm.BinaryExpression]]:
        return self.get_orm_clean_filters() | {
            Company: [self.get_companies_update_pred()],
            Naics: []}

    def get_artifacts_pred(self) -> orm.BinaryExpression:
        return Artifact.path.startswith(f'{self.state.lower()}/')

    def get_companies_delete_pred(self) -> orm.BinaryExpression:
        return Company.id.not_in(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state != self.state))

    def get_companies_update_pred(self) -> orm.BinaryExpression:
        return Company.id.in_(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state == self.state))

    @staticmethod
    def truncate_fields(record: dict[str, Any]) -> dict[str, int]:
        trims = {}
        for field in ('action', 'location', 'company', 'url'):
            value = record.get(field)
            limit = Report.__table__._columns[field].type.length
            if value and len(value) > limit:
                trims[field] = len(value) - limit
                record[field] = value[:limit]
        return trims
   
class PipelineRunner:
    GROUPING: ClassVar[Mapping[Stage, int]] = MapProxy({
        Stage.Scrape: 0,
        Stage.Extract: 1,
        Stage.Translate: 1,
        Stage.Load: 2,
        Stage.Index: 3})

    def __init__(self, stages: Iterable[Stage], states: Iterable[StateCode], **kw) -> None:
        context = kw.pop('context', None)
        if context is None:
            context = {}
        self.log = PipelineLog(
            id=uuid.uuid4(),
            stages=list(utils.unique(map(Stage, stages))),
            states=list(utils.unique(map(str.upper, states))),
            batch_opts=PipelineBatchOpts(**kw),
            pipeline_opts=PipelineOpts(**kw))
        self.log.context = context
        self.runs: dict[StateCode, list[PipelineRunDetail]] = defaultdict(list)
        self.logbackend = PipelineLogBackend.registry['mongo'](context=context)
        self.states_active = dict.fromkeys(self.states)

    @property
    def num_workers(self):
        return min(int(max(1, self.opts.max_workers)), len(self.states_active))

    @property
    def num_threads(self):
        return min(int(max(1, self.opts.max_threads)), len(self.states_active))

    @property
    def opts(self):
        return self.log.batch_opts

    @property
    def states(self):
        return self.log.states

    @property
    def stages(self):
        return self.log.stages

    @property
    def context(self):
        return self.log.context

    @property
    def pipeline_opts(self):
        return self.log.pipeline_opts

    async def run(self) -> None:
        self.run = None
        grouping: tuple[list[Stage], ...] = tuple(
            [] for _ in set(self.GROUPING.values()))
        for stage in self.stages:
            grouping[self.GROUPING[stage]].append(stage)
        it = iter(grouping)
        self.log.start = utils.utcnow()
        if await self._save_log():
            logger.info(f'start id={self.log.id}')
        try:
            await self.run_concurrently(True, *next(it))
            await self.run_concurrently(False, *next(it))
            await self.run_consecutively(*next(it))
            await self.run_concurrently(False, *next(it))
        except* Exception as grp:
            if not self.log.errors:
                exc = grp.exceptions[-1]
                error = PipelineRunError.fromexc(exc)
                self.log.errors.append(error)
            if len(grp.exceptions) == 1:
                raise grp.exceptions[0] from None
            raise
        finally:
            self.log.end = utils.utcnow()
            if await self._save_log():
                logger.info(f'end id={self.log.id}')

    async def run_consecutively(self, *stages: Stage) -> None:
        for state in tuple(self.states_active):
            await self.run_stages(state, *stages)
            await self._save_log()

    async def run_concurrently(self, threads: bool, *stages: Stage) -> None:
        style = 'threads' if threads else 'workers'
        num: int = getattr(self, f'num_{style}')
        if not (
            self.states_active and stages and self.opts.concurrent and num > 1):
            return await self.run_consecutively(*stages)
        logger.info(f'concurrent {style}={num} stages=[{', '.join(map(str, stages))}]')
        if threads:
            await self._run_thread_concurrently(*stages)
        else:
            await self._run_loop_concurrently(*stages)
        await self._save_log()

    async def _run_thread_concurrently(self, *stages: Stage) -> None:
        args = (deque(self.states_active), excs := [], *stages)
        workers = [
            Thread(name=str(i + 1), target=self.thread_worker, args=args)
            for i in range(self.num_threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        if excs:
            if len(excs) == 1:
                raise excs[0] from None
            raise ExceptionGroup(f'Encountered multiple exceptions', excs)

    async def _run_loop_concurrently(self, *stages: Stage) -> None:
        queue = deque(self.states_active)
        try:
            async with asyncio.TaskGroup() as group:
                for i in range(self.num_workers):
                    coro = self.loop_worker(queue, *stages)
                    group.create_task(coro, name=str(i + 1))
        except* Exception as errgrp:
            if len(errgrp.exceptions) == 1:
                raise errgrp.exceptions[0] from None
            raise

    async def run_stages(self, state: StateCode, *stages: Stage) -> None:
        for stage in stages:
            await self.run_stage(state, stage)
            if (reason := self._skip_reason(state)):
                logger.info(f'{state}:skip {reason}: {stage}')
                self.states_active.pop(state, None)
                break

    async def run_stage(self, state: StateCode, stage: Stage) -> None:
        if (reason := self._skip_reason(state)):
            logger.info(f'{state}:{stage}:skip {reason}')
            return
        run = PipelineRunDetail(state=state, stage=stage, start=utils.utcnow())
        self.runs[state].append(run)
        self.log.runs.append(run)
        try:
            pipeline = Pipeline(state, context=self.context, opts=self.pipeline_opts)
            if self.opts.stat_only:
                stat = await pipeline.stat(stage)
                logger.info(f'{state}:{stage}:stat {stat}')
            elif self.opts.clean_only:
                await pipeline.clean(stage)
            else:
                run.result = await pipeline.run(stage, clean=self.opts.clean)
        except Exception as err:
            run.error = PipelineRunError.fromexc(err, state=state, stage=stage)
            run.failed = True
            self.log.errors.append(run.error)
            if self.opts.fail:
                raise
            logger.exception(
                f'{state}:{stage}:fail error={run.error.model_dump(mode='json')}')
            capture_exception()
        finally:
            run.end = utils.utcnow()
            run.elapsed = (run.end - run.start).total_seconds()

    async def loop_worker(self, queue: deque[str], *stages: Stage) -> None:
        while queue and not (self.log.errors and self.opts.fail):
            state = queue.popleft()
            if state not in self.states_active:
                continue
            await self.run_stages(state, *stages)

    def thread_worker(self, queue: deque[str], excs: list[Exception], *stages: Stage) -> None:
        while not excs and queue and not (self.log.errors and self.opts.fail):
            try:
                state = queue.popleft()
            except IndexError:
                break
            if state not in self.states_active:
                continue
            try:
                asyncio.run(self.run_stages(state, *stages))
            except* Exception as grp:
                excs.extend(grp.exceptions)
                logger.error(f'Exiting thread due to error')

    async def _save_log(self) -> bool:
        self.log.sync()
        if self.opts.stat_only:
            return False
        await self.logbackend.save(self.log)
        return True

    def _skip_reason(self, state: StateCode) -> str|None:
        if (runs := self.runs[state]):
            run = runs[-1]
            if run.failed:
                return 'Previous stage failed'
            if self.opts.incremental:
                if run.result:
                    if run.result.get('nochange'):
                        return 'No change'
