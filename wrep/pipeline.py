from __future__ import annotations

import asyncio
import dataclasses
import functools
import operator
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path
from threading import Thread
from types import MappingProxyType as MapProxy
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from sentry_sdk import capture_exception

from . import SaveType, Stage, orm, settings, utils
from .backends.etl import *
from .models import *
from .orm import *
from .ref import normls

if TYPE_CHECKING:
    from .scrapers import Scraper
    from .translators import Translator

logger = utils.get_logger('pipeline')

class Pipeline:
    fields: ClassVar[tuple[str, ...]] = (
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
        'artifacts')
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
    json_types: ClassVar[Mapping[str, Callable[[Any], Any]]] = MapProxy({
        'id': uuid.UUID,
        'reported': datetime.fromisoformat,
        'starting': datetime.fromisoformat})
    BACKENDS: ClassVar[Mapping[Stage, type[StageBackend]]] = MapProxy(
        StageBackend.registry['mongo'])

    @dataclasses.dataclass
    class Opts:
        lazy: bool = True

    def __init__(self, state: StateCode, context: dict[str, Any]|None = None, **opts) -> None:
        if context is None:
            context = {}
        self.state = state.upper()
        self.context = context
        self.backends: dict[Stage, StageBackend] = {}
        self.opts = self.Opts(**opts)
        self.session: orm.Session|None = None

    @utils.lazyprop
    def scraper(self) -> Scraper:
        from .scrapers import scrapers
        return scrapers[self.state]()

    @utils.lazyprop
    def translator(self) -> Translator:
        from .translators import translators
        return translators[self.state]()

    def backend(self, stage: Stage) -> StageBackend:
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
            backend: SearchIndexBackend = self.backend(stage.Index)
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
        backend: ExtractionBackend = self.backend(stage)
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
        backend: TranslationBackend = self.backend(stage)
        source: ExtractionBackend = self.backend(stage.Extract)
        prev = await self.stat(stage)
        logger.info(f'{self.state}:{stage}:stat {prev}')
        if clean:
            await self.clean(stage)
        async with source.reader() as reader:
            with SessionLocal() as session:
                self.translator.session = session
                it = utils.amap(self.translator.entries, reader)
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
        source: TranslationBackend = self.backend(Stage.Translate)
        async with source.reader() as reader:
            with SessionLocal() as session:
                self.session = session
                if clean:
                    await self.clean(Stage.Load)
                async for entry in reader:
                    counts[self.save(entry)[1]] += 1
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
        backend: SearchIndexBackend = self.backend(stage)
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

    def save(self, entry: dict) -> tuple[Report|None, SaveType]:
        save = SaveType.Nochange
        record = {
            field: self.from_json(field, entry[field])
            for field in self.fields if field in entry}
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
        naics_save = self.save_naics(report, naics, industry)
        artifacts_save = self.save_artifacts(report, artifacts)
        if save is save.Nochange:
            values = (company_save, naics_save, artifacts_save)
            if any(value is not save.Nochange for value in values):
                save = save.Update
        if save is not save.Nochange:
            self.session.add(report)
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

    @classmethod
    def from_json(cls, field: str, value: Any) -> Any:
        if isinstance(value, str) and field in cls.json_types:
            value = cls.json_types[field](value)
        if isinstance(value, datetime) and not value.tzinfo:
            value = value.replace(tzinfo=timezone.utc)
        return value

class PipelineRunner:
    GROUPING: ClassVar[Mapping[Stage, int]] = MapProxy({
        Stage.Scrape: 0,
        Stage.Extract: 1,
        Stage.Translate: 1,
        Stage.Load: 2,
        Stage.Index: 3})

    def __init__(
        self,
        stages: Iterable[Stage|str],
        states: Iterable[StateCode],
        clean: bool = False,
        clean_only: bool = False,
        stat_only: bool = False,
        fail: bool = False,
        incremental: bool = False,
        concurrent: bool = False,
        max_workers: int = settings.ETL_DEFAULT_WORKERS,
        context: dict[str, Any]|None = None,
        **pipeline_opts,
    ) -> None:
        if clean_only and (clean or incremental or stat_only):
            raise ValueError(f'Cannot specify clean_only with clean, incremental, or stat_only')
        if stat_only and (clean or incremental or clean_only):
            raise ValueError(f'Cannot specify stat_only with clean, incremental, or clean_only')
        if context is None:
            context = {}
        self.id = uuid.uuid4()
        self.clean = clean
        self.clean_only = clean_only
        self.stat_only = stat_only
        self.incremental = incremental
        self.concurrent = concurrent
        self.max_workers = int(max(1, max_workers))
        self.fail = fail
        self.stages = list(utils.unique(map(Stage, stages)))
        self.states = list(utils.unique(map(str.upper, states)))
        self.errors: list[dict[str, str]] = []
        self.runs: dict[StateCode, list[dict]] = defaultdict(list)
        self.grouping: tuple[list[Stage], ...] = tuple(
            [] for _ in set(self.GROUPING.values()))
        for stage in self.stages:
            self.grouping[self.GROUPING[stage]].append(stage)
        self.num_workers = min(self.max_workers, len(self.states))
        self.context = context
        self.logbackend = PipelineLogBackend.registry['mongo'](context=self.context)
        self.pipeline_opts = pipeline_opts
        self.info = dict(
            id=self.id,
            stages=self.stages,
            states=self.states,
            batch_opts=dict(
                incremental=self.incremental,
                concurrent=self.concurrent,
                clean=self.clean,
                fail=self.fail,
                clean_only=self.clean_only,
                max_workers=self.max_workers),
            context=self.context,
            pipeline_opts=self.pipeline_opts,
            runs=[])
        self.start: datetime|None = None
        self.end: datetime|None = None

    async def run(self) -> None:
        self.run = None
        it = iter(self.grouping)
        self.start = utils.now()
        if await self._save_log():
            logger.info(f'start id={self.id}')
        try:
            await self.run_concurrently(True, *next(it))
            await self.run_concurrently(False, *next(it))
            await self.run_consecutively(*next(it))
            await self.run_concurrently(False, *next(it))
        finally:
            self.end = utils.now()
            if await self._save_log():
                logger.info(f'end id={self.id}')

    async def run_consecutively(self, *stages: Stage) -> None:
        for state in self.states:
            await self.run_stages(state, *stages)
            await self._save_log()

    async def run_concurrently(self, threads: bool, *stages: Stage) -> None:
        if not (stages and self.concurrent and self.num_workers > 1):
            return await self.run_consecutively(*stages)
        style = 'threads' if threads else 'workers'
        logger.info(f'concurrent {style}={self.num_workers} stages=[{', '.join(map(str, stages))}]')
        if threads:
            await self._run_thread_concurrently(*stages)
        else:
            await self._run_loop_concurrently(*stages)
        await self._save_log()

    async def _run_thread_concurrently(self, *stages: Stage) -> None:
        args = (deque(self.states), excs := [], *stages)
        workers = [
            Thread(name=str(i + 1), target=self.thread_worker, args=args)
            for i in range(self.num_workers)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        if excs:
            if len(excs) == 1:
                raise excs[0] from None
            raise ExceptionGroup(f'Encountered multiple exceptions', excs)

    async def _run_loop_concurrently(self, *stages: Stage) -> None:
        queue = deque(self.states)
        try:
            async with asyncio.TaskGroup() as group:
                for i in range(self.num_workers):
                    group.create_task(
                        self.loop_worker(queue, *stages),
                        name=str(i + 1))
        except* Exception as errgrp:
            if len(errgrp.exceptions) == 1:
                raise errgrp.exceptions[0] from None
            raise

    async def run_stages(self, state: StateCode, *stages: Stage) -> None:
        for stage in stages:
            await self.run_stage(state, stage)

    async def run_stage(self, state: StateCode, stage: Stage) -> None:
        if (reason := self._skip_reason(state)):
            logger.info(f'{state}:{stage}:skip {reason}')
            return
        start = utils.now()
        res = dict(state=state, stage=stage, start=start, end=None)
        try:
            pipeline = Pipeline(state, context=self.context, **self.pipeline_opts)
            if self.stat_only:
                stat = await pipeline.stat(stage)
                logger.info(f'{state}:{stage}:stat {stat}')
                return
            res.update(seq=len(self.info['runs']))
            self.runs[state].append(res)
            self.info['runs'].append(res)
            if self.clean_only:
                res.update(clean_only=True)
                await pipeline.clean(stage)
            else:
                res.update(await pipeline.run(stage, clean=self.clean))
        except Exception as err:
            error = dict(type=type(err).__name__, msg=str(err))
            res.update(failed=True, error=error)
            self.errors.append(dict(state=state, stage=stage)|error)
            logger.exception(f'{state}:{stage}:fail {error=}', exc_info=not self.fail)
            if self.fail:
                raise
            capture_exception()
        finally:
            end = utils.now()
            res.update(end=end, elapsed=(end - start).total_seconds())

    def getlog(self) -> dict[str, Any]:
        doc = dict(self.info)
        runs = list(doc.pop('runs'))
        until = self.end or utils.now()
        doc.update(start=self.start, end=self.end, elapsed=(until - self.start).total_seconds())
        if self.errors:
            doc.update(errors=self.errors)
            if self.fail:
                doc.update(error=self.errors[-1])
        doc.update(runs_count=len(runs), runs=runs)
        return doc

    async def loop_worker(self, queue: deque[str], *stages: Stage) -> None:
        while queue and not(self.errors and self.fail):
            await self.run_stages(queue.popleft(), *stages)

    def thread_worker(self, queue: deque[str], excs: list[Exception], *stages: Stage) -> None:
        while queue and not(self.errors and self.fail) and not excs:
            try:
                state = queue.popleft()
            except IndexError:
                break
            try:
                asyncio.run(self.run_stages(state, *stages))
            except Exception as err:
                excs.append(err)
                logger.error(f'Exiting thread due to error')
                break

    async def _save_log(self) -> bool:
        if self.stat_only:
            return False
        await self.logbackend.save(self.getlog())
        return True

    def _skip_reason(self, state: StateCode) -> str|None:
        if (runs := self.runs[state]):
            res = runs[-1]
            if res.get('failed'):
                return 'Previous stage failed'
            if self.incremental and res.get('nochange'):
                return 'No change'


class Command(utils.BaseCommand):
    description = """
    Run pipeline stages.
    
    Basic Examples
    --------------

    Run single stage for all states:
    $ {prog} scrape

    Run single stage for some states:
    $ {prog} extract CA NY

    Run all stages for some states:
    $ {prog} all FL OH

    Run all stages for all states:
    $ {prog} all

    Selecting Stages
    -----------------

    Available stages: """ + ', '.join(Stage) + """

    Specify multiple stages with a comma:
    $ {prog} scrape,extract [state ...]

    Using first letter with comma:
    $ {prog} s,e,t [state ...]

    With capital first letters, separator is unnecessary:
    $ {prog} SETL [state ...]

    Use keyword "all" for all stages:
    $ {prog} all [state ...]

    Available States
    ----------------
    {states}"""

    usage = '{prog} [OPTIONS] <stages> [state ...]'


    @classmethod
    def parser_fmtargs(cls, parser):
        from .scrapers import scrapers
        return super().parser_fmtargs(parser) | dict(
            states=' '.join(sorted(scrapers)))

    @classmethod
    def add_arguments(cls, parser):
        arg = parser.add_argument
        arg('stages',
            metavar='<stages>',
            type=cls.stages_opt,
            help='Stage name(s) (various formats) or "all"')
        arg('states',
            nargs='*',
            metavar='state',
            help=(
                'Optionally specify states as additional arguments. '
                'If not specified, include all states'))
        arg('--clean', '-c',
            action='store_true',
            help='Clean each stage before running')
        arg('--incremental', '-i',
            action='store_true',
            help=(
                'If a stage indicates no change after running, '
                'skip subsequent stages for the state'))
        arg('--concurrent', '-t',
            action='store_true',
            help=(
                'Use multiple async workers when applicable. '
                'The load stage is always synchronized with one worker'))
        arg('--nofail', '-n',
            action='store_false',
            dest='fail',
            help=(
                'Do not fail on error. Instead, log an exception, '
                'and skip subsequent stages for the state'))
        arg('--clean-only', '-x',
            action='store_true',
            help='Only clean, do not run')
        arg('--stat-only', '-s',
            action='store_true',
            help='Only show stats, do not run')
        arg('--search-dbname', '-d',
            default=None,
            help=f'Alternate mongo search db name')
        arg('--etl-dbname', '-b',
            default=None,
            help=f'Alternate mongo etl db name')
        arg('--max-workers', '-w',
            type=int,
            metavar='<n>',
            default=settings.ETL_DEFAULT_WORKERS,
            help=(
                'Max workers, applicable only when --concurrent is specified, '
                f'default ETL_DEFAULT_WORKERS ({settings.ETL_DEFAULT_WORKERS})'))
        arg('--eager', '-e',
            action='store_false',
            dest='lazy',
            help='Use eager loading of SQL result sets. Uses more memory')
        arg('--idfile',
            default=None,
            type=Path,
            help='Write the pipeline log ID to the given file')

    def setup(self, opts):
        from .backends import etl
        from . import search
        from .scrapers import scrapers
        opts.states = opts.states or sorted(scrapers)
        runner_opts = dict(vars(opts))
        self.idfile: Path|None = runner_opts.pop('idfile')
        runner_opts['context'] = {
            etl.client.dbname_key: runner_opts.pop('etl_dbname'),
            search.client.dbname_key: runner_opts.pop('search_dbname')}
        self.runner = PipelineRunner(**runner_opts)

    async def run(self):
        if self.idfile:
            logger.info(f'Writing pipeline log ID to {self.idfile}')
            self.idfile.write_text(str(self.runner.id))
        await self.runner.run()

    @staticmethod
    def stages_opt(value: str) -> list[Stage]:
        if value == 'all':
            return list(Stage)
        value = value.replace(',', ' ')
        for stage in Stage:
            value = value.replace(stage[0].upper(), f' {stage.value} ')
        trans = {stage[0]: stage for stage in Stage}
        return [Stage(trans.get(value, value)) for value in value.split()]
