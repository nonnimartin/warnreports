from __future__ import annotations

import asyncio
import functools
import operator
import time
import uuid
from collections import defaultdict, deque
from enum import StrEnum
from functools import cache
from functools import cached_property as lazy
from itertools import chain
from pathlib import Path
from threading import Thread
from types import CoroutineType
from types import MappingProxyType as MapProxy
from typing import TYPE_CHECKING, Any, AsyncIterable, Iterable, Mapping

from sentry_sdk import capture_exception

from . import SaveType, Stage, orm, scrapers, utils
from .backends import etl, mongo
from .backends.etl import *
from .models import *
from .orm import *
from .ref import normls

if TYPE_CHECKING:
    from typing import overload

type OrmFiltersDict = dict[type[orm.MapReduceBase], list[orm.BinaryExpression]]

class Pipeline:
    required_fields: ClassVar[list[str]] = ['company', 'reported']
    'Required fields to save a translation'
    write_fields: ClassVar[list[str]] = required_fields + [
        'location', 'starting', 'employees', 'action', 'url']
    'Writeable database fields when saving a translation'

    def __init__(self, state: StateCode, *, context: dict[str, Any]|None = None, opts: PipelineOpts|Any = None) -> None:
        if context is None:
            context = {}
        self.state = ValidStateCode(state)
        self.context = context
        self.opts = PipelineOpts.model_validate(opts or {})
        self.session: orm.Session|None = None
        self.logger = utils.get_logger(f'pipeline.{self.state}')

    if TYPE_CHECKING:
        @overload
        def backend[B: StageBackend](self, base: type[B]) -> B:...

    @cache
    def backend[B: StageBackend](self, base: type[B]) -> B:
        return StageBackend.registry['mongo'][base.stage](context=self.context)

    @lazy
    def scraper(self) -> scrapers.ScraperType:
        return scrapers.registry[self.state](opts=self.opts)

    async def run(self, stage: Stage, clean: bool = False) -> dict:
        stage = Stage(stage)
        self.logger.info(f'{stage}:start')
        summary: dict = await getattr(self, stage)(clean=clean)
        self.logger.info(f'{stage}:complete {summary}')
        return summary

    async def stat(self, stage: Stage) -> dict:
        stage = Stage(stage)
        state = self.state
        if stage is stage.Scrape:
            return await self.scraper.stat()
        if stage is stage.Extract:
            backend = self.backend(ExtractionBackend)
            return await backend.stat(dict(state=state))
        if stage is stage.Translate:
            backend = self.backend(TranslationBackend)
            return await backend.stat(dict(state=state))
        if stage is stage.Load:
            stat: dict[str, int] = {}
            backend = self.backend(SearchIndexBackend)
            filters = self.get_orm_select_filters(state=state)
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
        if stage is stage.Index:
            backend = self.backend(SearchIndexBackend)
            coros = {
                name: backend.stat(name, dict(state=state))
                for name in ('reports', 'artifacts', 'companies')}
            return {k: await v for k, v in coros.items()}
        raise ValueError(stage)
        
    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        state = self.state
        self.logger.info(f'{stage}:clean')
        if stage is stage.Scrape:
            await self.scraper.clean()
        elif stage is stage.Extract:
            backend = self.backend(ExtractionBackend)
            await backend.clean(dict(state=state))
            await self.scraper.extract_clean()
        elif stage is stage.Translate:
            backend = self.backend(TranslationBackend)
            await backend.clean(dict(state=state))
        elif stage is stage.Load:
            filters = self.get_orm_clean_filters(state=state)
            stmts = (
                orm.delete(model).where(*filters)
                for model, filters in filters.items())
            with ensure_session(self.session) as session:
                for stmt in stmts:
                    session.execute(stmt)
                if not self.session and not self.opts.rollback:
                    session.commit()
        elif stage is stage.Index:
            backend = self.backend(SearchIndexBackend)
            coros = [
                backend.clean('reports', dict(state=state)),
                backend.clean('artifacts', dict(state=state)),
                backend.clean('companies', dict(
                    state=state,
                    states_count_min=1,
                    states_count_max=1)),
                backend.clean('states', dict(id=state))]
            for coro in coros:
                await coro
        self.logger.info(f'{stage}:clean:complete')

    async def scrape(self, clean: bool = False) -> dict:
        stage = Stage.Scrape
        prev = await self.stat(stage)
        self.logger.info(f'{stage}:stat {statlog(prev)}')
        if clean:
            await self.clean(stage)
        scraper = self.scraper
        await scraper.scrape()
        metrics = dict(scraper.metrics)
        if scraper.artifacts.metrics:
            metrics.update(artifacts=dict(scraper.artifacts.metrics))
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        res = dict(nochange=nochange, prev=statlog(prev), cur=statlog(cur))
        if metrics:
            res.update(metrics=metrics)
        return res

    async def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        state = self.state
        backend = self.backend(ExtractionBackend)
        prev = await self.stat(stage)
        self.logger.info(f'{stage}:stat {statlog(prev)}')
        if clean:
            await self.clean(stage)
        scraper = self.scraper
        async with utils.awith(scraper.extract()) as source:
            it = utils.as_aiter(source)
            it = (dict(state=state, data=x) async for x in it)
            count, created, updated = await backend.update(it)
            deleted = await backend.clean(dict(state=[state], i_min=count+1))
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        counts = dict(count=count, created=created, updated=updated, deleted=deleted)
        return dict(nochange=nochange) | counts | dict(prev=statlog(prev), cur=statlog(cur))

    async def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        state = self.state
        backend = self.backend(TranslationBackend)
        source = self.backend(ExtractionBackend)
        prev = await self.stat(stage)
        self.logger.info(f'{stage}:stat {statlog(prev)}')
        if clean:
            await self.clean(stage)
        from .translators import TranslationFactory
        reader: AsyncIterable[Extraction]
        async with source.reader(dict(state=state)) as reader:
            with SessionLocal() as session:
                factory = TranslationFactory(session)
                it = (x.model_dump(mode='json') async for x in reader)
                it = utils.amap(factory.translate, it)
                it = utils.achain_from_iterable(it)
                count, created, updated = await backend.update(it)
                if self.opts.rollback:
                    session.rollback()
                else:
                    session.commit()
        cur = await self.stat(stage)
        nochange = cur == prev if cur else None
        counts = dict(count=count, created=created, updated=updated)
        return dict(nochange=nochange) | counts | dict(prev=statlog(prev), cur=statlog(cur))

    async def load(self, clean: bool = False) -> dict:
        state = self.state
        counts = dict.fromkeys(map(str, SaveType), 0)
        self.artifact_cache = {}
        count = 0
        source = self.backend(TranslationBackend)
        async with source.reader(dict(state=state)) as reader:
            with SessionLocal() as session:
                self.session = session
                if clean:
                    await self.clean(Stage.Load)
                async for translation in reader:
                    counts[self.save(translation)[1]] += 1
                    count += 1
                    if not count % self.opts.load_per_tick:
                        await asyncio.sleep(0)
                stat = session.get(StateStat, state)
                stat = stat or StateStat(id=state)
                stat.self_update(session)
                session.add(stat)
                if self.opts.rollback:
                    session.rollback()
                else:
                    session.commit()
            self.session = None
        del self.artifact_cache
        nochange = count == counts[SaveType.Nochange] + counts[SaveType.Skip]
        return dict(nochange=nochange, count=count, counts=counts)

    async def index(self, clean: bool = False) -> dict:
        stage = Stage.Index
        state = self.state
        if clean:
            await self.clean(stage)
        backend = self.backend(SearchIndexBackend)
        filters = self.get_orm_select_filters(state=state)
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
            report = Report(id=uid, state=translation.state)
            save = save.Create
        naics = set(record.pop('naics', ()))
        industry = record.pop('industry', None)
        artifacts = record.pop('artifacts', {})
        self.truncate_fields(record)
        company, company_save = self.save_company(record['company'])
        record.update(company_norm_id=company.name_norm_id)
        dirty = save is save.Create
        for field in chain(self.write_fields, ('company_norm_id',)):
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
        if save is not save.Nochange:
            self.logger.debug(f'{save} {report.id} {report.reported.strftime(f'%Y-%m-%d')}')
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
            str(Path(f'{report.state.lower()}/{key}')): url
            for key, url in index.items()}
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

    def get_orm_clean_filters(self, state: StateCode) -> OrmFiltersDict:
        return {
            Report: [Report.state == state],
            Company: [self.get_companies_delete_pred(state=state)],
            Artifact: [self.get_artifacts_pred(state=state)],
            StateStat: [StateStat.id == state]}

    def get_orm_select_filters(self, state: StateCode) -> OrmFiltersDict:
        return self.get_orm_clean_filters(state=state) | {
            Company: [self.get_companies_update_pred(state=state)],
            Naics: []}

    def get_artifacts_pred(self, state: StateCode) -> orm.BinaryExpression:
        return Artifact.path.startswith(f'{state.lower()}/')

    def get_companies_delete_pred(self, state: StateCode) -> orm.BinaryExpression:
        return Company.id.not_in(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state != state))

    def get_companies_update_pred(self, state: StateCode) -> orm.BinaryExpression:
        return Company.id.in_(
            orm.select(Company.id)
            .join(Report, Report.company == Company.name)
            .where(Report.state == state))

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

def statlog(stat: dict):
    stat = dict(stat)
    stat.pop('hash', None)
    return stat

class SkipReason(StrEnum):
    fail = 'Previous stage failed'
    nochange = 'No change'

class PipelineRunner:
    GROUPING: ClassVar[Mapping[Stage, int]] = MapProxy({
        Stage.Scrape: 0,
        Stage.Extract: 1,
        Stage.Translate: 1,
        Stage.Load: 2,
        Stage.Index: 3})
    logger: ClassVar[utils.logging.Logger] = utils.get_logger('pipeline.runner')

    def __init__(
        self,
        stages: Iterable[Stage],
        states: Iterable[StateCode],
        context: dict[str, Any]|None = None,
        client: mongo.MongoClient|None = None,
        **kw
    ) -> None:
        if context is None:
            context = {}
        self.log = PipelineLog(
            stages=stages,
            states=states,
            batch_opts=PipelineBatchOpts(**kw),
            pipeline_opts=PipelineOpts(**kw))
        self.log.context = context
        self.runs: dict[StateCode, list[PipelineRunDetail]] = defaultdict(list)
        self.backend = etl.MongoPipelineLog(context=context, client=client)
        self.states_active = dict.fromkeys(self.states)
        self.lastsaved = 0.0
        self.saveinterval = 1.0
        self.sleepdelay = 0.005

    @property
    def num_workers(self) -> int:
        return min(self.opts.max_workers, len(self.states_active))

    @property
    def num_threads(self) -> int:
        return min(self.opts.max_threads, len(self.states_active))

    @property
    def opts(self) -> PipelineBatchOpts:
        return self.log.batch_opts

    @property
    def states(self) -> list[StateCode]:
        return self.log.states

    @property
    def stages(self) -> list[Stage]:
        return self.log.stages

    @property
    def context(self) -> dict[str, Any]:
        return self.log.context

    @property
    def pipeline_opts(self) -> PipelineOpts:
        return self.log.pipeline_opts

    async def run(self) -> None:
        self.run = None
        grouping: tuple[list[Stage], ...] = tuple(
            [] for _ in set(self.GROUPING.values()))
        for stage in self.stages:
            grouping[self.GROUPING[stage]].append(stage)
        it = iter(grouping)
        self.log.start = utils.utcnow()
        if await self.savelog(now=True):
            self.logger.info(f'start id={self.log.id}')
        try:
            await self.pollsave(self.run_concurrently(True, *next(it)))
            await self.pollsave(self.run_concurrently(False, *next(it)))
            await self.pollsave(self.run_consecutively(*next(it)))
            await self.pollsave(self.run_concurrently(False, *next(it)))
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
            if await self.savelog(now=True):
                self.logger.info(f'end id={self.log.id}')

    async def run_consecutively(self, *stages: Stage) -> None:
        for state in tuple(self.states_active):
            await self.run_stages(state, *stages)

    async def run_concurrently(self, threads: bool, *stages: Stage) -> None:
        style = 'threads' if threads else 'workers'
        num: int = getattr(self, f'num_{style}')
        if not (
            self.states_active and
            stages and
            self.opts.concurrent and
            num > 1
        ):
            return await self.run_consecutively(*stages)
        self.logger.info(f'concurrent {style}={num} stages=[{', '.join(map(str, stages))}]')
        if threads:
            await self.run_thread_concurrently(*stages)
        else:
            await self.run_loop_concurrently(*stages)

    async def run_thread_concurrently(self, *stages: Stage) -> None:
        queue = deque(self.states_active)
        excs: list[Exception] = []
        def target() -> None:
            while True:
                if excs or self.log.errors and self.opts.fail:
                    break
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
                    self.logger.error(f'Exiting thread due to error')
        names = map(str, range(1, self.num_threads + 1))
        threads = [Thread(name=n, target=target) for n in names]
        for thread in threads:
            thread.start()
        while (active := sum(thread.is_alive() for thread in threads)):
            await asyncio.sleep(self.sleepdelay * min(10, active))
        if excs:
            if len(excs) == 1:
                raise excs[0] from None
            raise ExceptionGroup(f'Encountered multiple exceptions', excs)

    async def run_loop_concurrently(self, *stages: Stage) -> None:
        queue = deque(self.states_active)
        async def worker() -> None:
            while True:
                if self.log.errors and self.opts.fail:
                    break
                try:
                    state = queue.popleft()
                except IndexError:
                    break
                if state not in self.states_active:
                    continue
                await self.run_stages(state, *stages)
        try:
            async with asyncio.TaskGroup() as group:
                for i in range(self.num_workers):
                    group.create_task(worker(), name=str(i + 1))
        except* Exception as errgrp:
            if len(errgrp.exceptions) == 1:
                raise errgrp.exceptions[0] from None
            raise

    async def run_stages(self, state: StateCode, *stages: Stage) -> None:
        for stage in stages:
            await self.run_stage(state, stage)
            if (reason := self.skipreason(state)):
                self.logger.info(f'{state}:skip {reason}: {stage}')
                self.states_active.pop(state, None)
                break

    async def run_stage(self, state: StateCode, stage: Stage) -> None:
        if (reason := self.skipreason(state)):
            self.logger.info(f'{state}:{stage}:skip {reason}')
            self.states_active.pop(state, None)
            return
        run = PipelineRunDetail(state=state, stage=stage, start=utils.utcnow())
        self.runs[state].append(run)
        self.log.runs.append(run)
        try:
            pipeline = Pipeline(state, context=self.context, opts=self.pipeline_opts)
            if self.opts.stat_only:
                stat = await pipeline.stat(stage)
                self.logger.info(f'{state}:{stage}:stat {stat}')
            elif self.opts.clean_only:
                await pipeline.clean(stage)
            else:
                run.result = await pipeline.run(stage, clean=self.opts.clean)
        except Exception as err:
            run.error = PipelineRunError.fromexc(err, state=state, stage=stage)
            run.failed = True
            self.log.errors.append(run.error)
            if self.opts.fail:
                self.logger.error(f'{run.error}')
                raise
            self.logger.exception(f'{state}:{stage}:fail error={err!r}')
            capture_exception()
        finally:
            run.end = utils.utcnow()
            run.sync()

    async def pollsave[T](self, coro: CoroutineType[Any, Any, T]) -> T:
        task = asyncio.create_task(coro)
        while not task.done():
            if not await self.savelog():
                await asyncio.sleep(self.sleepdelay)
        return await task

    async def savelog(self, *, now: bool = False) -> bool:
        if not now and time.monotonic() - self.lastsaved < self.saveinterval:
            return False
        self.lastsaved = time.monotonic()
        self.log.sync()
        if self.opts.stat_only:
            return False
        await self.backend.save(self.log)
        return True

    def skipreason(self, state: StateCode) -> SkipReason|None:
        if (runs := self.runs[state]):
            run = runs[-1]
            if run.failed:
                return SkipReason.fail
            if (
                self.opts.incremental and
                run.result and
                run.result.get('nochange')
            ):
                return SkipReason.nochange
