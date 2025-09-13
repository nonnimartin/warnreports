from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any, Callable, ClassVar, Mapping
from uuid import UUID

import yaml

from .. import orm, utils
from ..backends import etl
from ..models import *
from .base import AP, AppCommand, BaseCommand, NonNegIntTa, PosIntTa
from .mongo import ClientControlCommand

logger = logging.getLogger(__name__)

class EtlBaseCommand(AppCommand):
    output_formats: ClassVar[list[str]] = ['json', 'yaml']
    default_format: ClassVar[str] = 'json'

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        arg = parser.add_argument
        arg(
            '--etl-dbname', '-b',
            default=None,
            help=f'Alternate mongo etl db name')
        arg(
            '--output', '-o',
            choices=cls.output_formats,
            default=cls.default_format,
            help=f'Output format, default {cls.default_format}')
        if 'table' in cls.output_formats:
            arg(
                '--tablefmt',
                default='simple',
                help=f'Table format')
        super().add_arguments(parser)

    def setup(self, opts) -> None:
        super().setup(opts)
        self.output: str = opts.output
        self.context = {etl.default_client.dbname_key: opts.etl_dbname}

    def printobj(self, obj: Any) -> None:
        print(self.objtext(obj))

    def objtext(self, obj: Any) -> str:
        if isinstance(obj, str):
            text = obj
        elif self.output == 'yaml':
            text = yaml.safe_dump(obj, sort_keys=False)
        else:
            text = json.dumps(obj, indent=2)
        return text

    def tablulate(self, body: Any, head: Any) -> str:
        from tabulate import tabulate
        tablefmt = getattr(self.opts, 'tablefmt', 'simple')
        return tabulate(body, head, tablefmt=tablefmt, floatfmt='.2f')

class OneCommand(BaseCommand):

    class Base(EtlBaseCommand):
        label: ClassVar[str] = '?'
        backend_class: ClassVar[type[etl.MongoETBase]]
        idopt: ClassVar[Callable[[str], UUID]] = UUID
        idopt_help: ClassVar[str|None] = None

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            arg = parser.add_argument
            arg(
                '--save', '-s',
                action='store_true',
                help='Save the result')
            arg(
                'id',
                type=cls.idopt,
                help=cls.idopt_help or f'The {cls.label} doc id')
            super().add_arguments(parser)

        def setup(self, opts) -> None:
            super().setup(opts)
            self.backend = self.backend_class(context=self.context)

        async def get_inst(self) -> etl.ETBase:
            srch = self.backend.search(dict(id=self.opts.id), limit=1)
            try:
                return await anext(srch.objs())
            except StopAsyncIteration:
                raise ValueError(f'Doc not found: {self.opts.id}')

    class Trone(Base):
        'Run translations for a single extraction doc, and print the result'
        label = 'extraction'
        backend_class: ClassVar[type[etl.MongoExtraction]] = etl.MongoExtraction
        idopt_help = 'The extraction doc id, or state & sequence (e.g. WI.123)'

        @classmethod
        def idopt(cls, value: str) -> UUID:
            if '.' in value:
                state, i = value.rsplit('.', 1)
                if len(state) != 2:
                    raise ValueError(f'{state=}')
                return cls.backend_class.get_seq_id(state, int(i))
            return super().idopt(value)

        async def run(self) -> None:
            from ..translators import TranslationFactory
            extraction = await self.get_inst()
            with orm.SessionLocal() as session:
                factory = TranslationFactory(session)
                translations = list(factory.translate(extraction.model_dump()))
                res = dict(
                    translations=[
                        x.model_dump(
                            mode='json',
                            exclude_unset=True,
                            exclude_none=True,
                            exclude=['extraction'])
                        for x in translations],
                    extraction=extraction.model_dump(mode='json'))
                self.printobj(res)
                if self.opts.save:
                    backend = etl.MongoTranslation(context=self.context)
                    await backend.update(translations)
                    session.commit()
                else:
                    session.rollback()

        async def get_inst(self) -> Extraction:
            try:
                return await super().get_inst()
            except ValueError:
                logger.warning(f'Extraction {self.opts.id} not found, checking translations')
            backend = etl.MongoTranslation(context=self.context)
            srch = backend.search(dict(id=self.opts.id), limit=1)
            try:
                translation = await anext(srch.objs())
            except StopAsyncIteration:
                raise ValueError(f'Doc not found: {self.opts.id}')
            self.opts.id = translation.extraction.id
            return await super().get_inst()

    class Ldone(Base):
        'Run load operations for a single translation doc, and print the result'
        label = 'translation'
        backend_class = etl.MongoTranslation

        async def run(self) -> None:
            translation: Translation = await self.get_inst()
            # Lazy import for etl requirements separation
            from ..pipeline import Pipeline
            pipeline = Pipeline(translation.state, context=self.context)
            with orm.SessionLocal() as session:
                pipeline.session = session
                pipeline.artifact_cache = {}
                report, save = pipeline.save(translation)
                if report is not None:
                    row = (report, report, None, None)
                    report, = orm.Report.map_reduce([row])
                res = dict(
                    save=str(save),
                    report=report.model_dump(
                        mode='json',
                        exclude_unset=True),
                    translation=translation.model_dump(
                        mode='json',
                        exclude_none=True,
                        exclude=['extraction']),
                    extraction=translation.extraction.model_dump(
                        mode='json'))
                self.printobj(res)
                if self.opts.save and save is not save.Nochange:
                    session.commit()
                else:
                    session.rollback()

    commands = dict(trone=Trone, ldone=Ldone)

class LogCommand(BaseCommand):
    'Pipeline log commands'

    class Base(EtlBaseCommand):

        def setup(self, opts) -> None:
            super().setup(opts)
            self.backend = etl.MongoPipelineLog(context=self.context)

    class List(Base):
        'List pipeline logs'
        output_formats: ClassVar[list[str]] = EtlBaseCommand.output_formats + ['table']
        default_format: ClassVar[str] = 'table'
        headers: ClassVar[list[str]] = ['id', 'start', 'states', 'stages', 'runs', 'errors', 'elapsed']

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            arg = parser.add_argument
            arg(
                '--limit', '-l',
                default=10,
                type=PosIntTa.validate_strings,
                help=f'Results limit, default 10')
            arg(
                '--skip', '-s',
                default=0,
                dest='offset',
                type=NonNegIntTa.validate_strings,
                help=f'Skip n results (offset)')
            super().add_arguments(parser)

        async def run(self) -> None:
            kw = dict(limit=self.opts.limit, offset=self.opts.offset)
            srch = self.backend.search({}, **kw)
            results = [
                dict(zip(self.headers, map(x.get_short().get, self.headers)))
                async for x in srch.objs()]
            if self.output == 'table':
                head = dict(zip(self.headers, self.headers))
                body = self.tablulate(results, head)
            else:
                body = dict(results=results)
            self.printobj(body)

    class Show(Base):
        'Show pipeline log'
        output_formats: ClassVar[list[str]] = EtlBaseCommand.output_formats + ['table']
        summary_methods: ClassVar[dict[str, str]] = {
            'short': 'get_short',
            'runs': 'get_runs',
            'running': 'get_running',
            'load-changes': 'get_load_changes',
            'scrape-stats': 'get_scrape_stats'}
        summary_fields: ClassVar[dict[str, tuple[str, ...]|dict[str, Any]]] = {
            'short': dict(key=0, value=1),
            'runs': ('stage', 'state', 'elapsed', 'failed', 'nochange'),
            'running': ('stage', 'state', 'elapsed', 'failed'),
            'load-changes': ('state', 'created', 'updated'),
            'scrape-stats': ('state', 'elapsed', 'request_count', 'request_bytes')}

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            arg = parser.add_argument
            arg(
                '--summary', '-s',
                choices=cls.summary_methods,
                default=None,
                help=(f'The summary type to show'))
            arg(
                '--verbose', '-v',
                action='store_true',
                help=f'Verbose output')
            arg(
                '--watch', '-w',
                nargs='?',
                metavar='interval',
                default=False,
                help=f'Watch')
            arg(
                'id',
                type=UUID,
                nargs='?',
                default=None,
                help='The pipeline log ID, default latest')
            super().add_arguments(parser)

        def setup(self, opts) -> None:
            super().setup(opts)
            self.verbose: bool = opts.verbose
            self.summary: str|None = opts.summary
            self.watch: utils.Delta|None = (
                None if opts.watch is False else
                utils.deltaparse(opts.watch or '5s', default_unit='seconds'))
            if not self.summary and self.output == 'table':
                self.parser.error(f'Table output only supported with summary')
            if self.verbose:
                if self.summary:
                    self.parser.error(f'Verbose output not supported with summary')
                if self.output == 'table':
                    self.parser.error(f'Verbose output not supported with table output')

        async def run(self) -> None:
            if self.opts.id:
                log = await self.backend.fetch(self.opts.id)
            else:
                log = await self.backend.fetch_latest()
            try:
                while True:
                    if self.watch and sys.stdout.isatty():
                        os.system('clear')
                    if self.summary:
                        body = getattr(log, self.summary_methods[self.summary])()
                        if self.output == 'table':
                            body = self.output_table(body)
                    else:
                        body = self.default_body(log)
                    self.printobj(body)
                    if log.end or not self.watch:
                        break
                    await asyncio.sleep(self.watch.total_seconds())
                    log = await self.backend.fetch(log.id)
            except KeyboardInterrupt:
                pass

        def output_table(self, body: dict) -> str:
            head = self.summary_fields[self.summary]
            if not isinstance(head, Mapping):
                head = dict(zip(head, head))
            if isinstance(body, Mapping):
                body = list(body.items())
            return self.tablulate(body, head)

        def default_body(self, log: PipelineLog) -> dict[str, Any]:
            body = log.model_dump(mode='json', exclude_none=True)
            if not self.verbose:
                body.update(runs=len(body['runs']), states=len(body['states']))
            return body

    class Copy(Base):
        'Copy pipeline logs to another db'

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            parser.add_argument('dest', help='The destination db name')
            super().add_arguments(parser)

        def setup(self, opts) -> None:
            super().setup(opts)
            self.src = self.backend
            self.dst = etl.MongoPipelineLog(context={next(iter(self.context)): opts.dest})

        async def run(self) -> None:
            src_db = await self.src.db()
            dst_db = await self.dst.db()
            if src_db.name == dst_db.name:
                raise ValueError(f'Source and dest db cannot be the same')
            logger.info(f'Copying from {src_db.name} to {dst_db.name}')
            res = await self.dst.update(self.src.search({}).objs())
            counts = dict(zip(('count', 'created', 'updated'), res))
            self.printobj(counts)

    class Prune(Base):
        'Prune old pipeline logs'

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            parser.add_argument(
                '--maxage', '-m',
                type=utils.deltaopt('days'),
                default='30d',
                help='Max age, default 30d')
            parser.add_argument(
                '--dryrun',
                action='store_true',
                help='Dry run only')
            super().add_arguments(parser)

        async def run(self) -> None:
            res = await self.backend.prune(self.opts.maxage, dryrun=self.opts.dryrun)
            result = dict(deleted=res)
            if self.opts.dryrun:
                result.update(dryrun=True)
            self.printobj(result)

    commands = dict(list=List, show=Show, copy=Copy, prune=Prune)

class Command(BaseCommand):
    'Misc ETL pipeline commands'
    commands = dict(
        log=LogCommand,
        **OneCommand.commands,
        control=ClientControlCommand(etl.default_client))
