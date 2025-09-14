from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import sys
from datetime import timedelta
from typing import Annotated, Any, ClassVar, Literal, Mapping, Self
from uuid import UUID

import yaml
from pydantic import (BeforeValidator, Field, PositiveFloat, field_validator,
                      model_validator)

from .. import orm, settings, utils
from ..backends import etl
from ..models import *
from .base import AP, AppCommand, BaseCommand, BaseCommandOpts
from .mongo import ClientControlCommand

logger = logging.getLogger(__name__)

class EtlCommandOpts(BaseCommandOpts):
    output: Literal['json', 'yaml'] = 'json'
    etl_dbname: str|None = None

class OneCommandOpts(EtlCommandOpts):
    id: UUID
    save: bool = False

class TrOneCommandOpts(OneCommandOpts):

    @field_validator('id', mode='before')
    @classmethod
    def idopt(cls, value: str|Any) -> UUID:
        value = str(value)
        if '.' in value:
            state, i = value.rsplit('.', 1)
            return etl.ExtractionBackend.get_seq_id(ValidStateCode(state), int(i))
        return UUID(value)

class LogSummaryMethod(enum.StrEnum):
    get_short = 'short'
    get_runs = 'runs'
    get_running = 'running'
    get_load_changes = 'load-changes'
    get_scrape_stats = 'scrape-stats'

class LogShowOpts(EtlCommandOpts):
    output: Literal['json', 'yaml', 'table'] = 'json'
    summary: LogSummaryMethod|None = None
    verbose: bool = False
    id: UUID|None = None
    watch: PositiveFloat|None = Field(False, validate_default=True)
    watch_default: ClassVar[PositiveFloat] = 5.0

    @field_validator('watch', mode='before')
    @classmethod
    def validate_watch(cls, value: Literal[False]|None|utils.Delta|Any) -> PositiveFloat|None:
        if value is False:
            return None
        if value is None:
            return cls.watch_default
        return utils.deltaparse(value, default_unit='seconds').total_seconds()

    @model_validator(mode='after')
    def check_compatibility(self) -> Self:
        if not self.summary and self.output == 'table':
            raise ValueError(f'Table output only supported with summary')
        if self.verbose:
            if self.summary:
                raise ValueError(f'Verbose output not supported with summary')
            if self.output == 'table':
                raise ValueError(f'Verbose output not supported with table output')
        return self

class LogListOpts(EtlCommandOpts):
    output: Literal['json', 'yaml', 'table'] = 'table'
    limit: Limit = 10
    offset: Offset = 0

class LogCopyOpts(EtlCommandOpts):
    dest: str

class LogPruneOpts(EtlCommandOpts):
    maxage: Annotated[
        timedelta,
        BeforeValidator(utils.deltaopt('days'))] = Field('30d', validate_default=True)
    dryrun: bool = False

class EtlBaseCommand[O: EtlCommandOpts](AppCommand[O]):
    output_formats: ClassVar[list[str]] = ['json', 'yaml']
    default_format: ClassVar[str] = 'json'
    options_class: ClassVar[type[O]] = EtlCommandOpts

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        arg = parser.add_argument
        arg(
            '--etl-dbname', '-b',
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

    def setup(self) -> None:
        super().setup()
        self.context = {settings.ETL_MONGODB_DBNAME_KEY: self.opts.etl_dbname}

    def printobj(self, obj: Any) -> None:
        print(self.objtext(obj))

    def objtext(self, obj: Any) -> str:
        if isinstance(obj, str):
            text = obj
        elif self.opts.output == 'yaml':
            text = yaml.safe_dump(obj, sort_keys=False)
        else:
            text = json.dumps(obj, indent=2)
        return text

    def tablulate(self, body: Any, head: Any) -> str:
        from tabulate import tabulate
        tablefmt = getattr(self.opts, 'tablefmt', 'simple')
        return tabulate(body, head, tablefmt=tablefmt, floatfmt='.2f')

class OneCommand(BaseCommand):

    class Base[O: OneCommandOpts](EtlBaseCommand[O]):
        label: ClassVar[str] = ''
        backend_class: ClassVar[type[etl.MongoETBase]]
        options_class: ClassVar[type[O]] = OneCommandOpts
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
                help=cls.idopt_help or f'The {cls.label} doc id')
            super().add_arguments(parser)

        def setup(self) -> None:
            super().setup()
            self.backend = self.backend_class(context=self.context)

        async def get_inst(self) -> etl.ETBase:
            srch = self.backend.search(dict(id=self.opts.id), limit=1)
            try:
                return await anext(srch.objs())
            except StopAsyncIteration:
                raise ValueError(f'Doc not found: {self.opts.id}')

    class Trone(Base[TrOneCommandOpts]):
        'Run translations for a single extraction doc, and print the result'
        backend_class: ClassVar[type[etl.MongoExtraction]] = etl.MongoExtraction
        options_class: ClassVar = TrOneCommandOpts
        label: ClassVar = 'extraction'
        idopt_help: ClassVar = 'The extraction doc id, or state & sequence (e.g. WI.123)'
        trdumpopts: ClassVar = dict(
            mode='json',
            exclude_unset=True,
            exclude_none=True,
            exclude=['extraction'])

        async def run(self) -> None:
            from ..translators import TranslationFactory
            extraction = await self.get_inst()
            with orm.SessionLocal() as session:
                factory = TranslationFactory(session)
                translations = list(factory.translate(extraction.model_dump()))
                self.printobj(dict(
                    translations=[
                        x.model_dump(**self.trdumpopts)
                        for x in translations],
                    extraction=extraction.model_dump(mode='json')))
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

    class Ldone(Base[OneCommandOpts]):
        'Run load operations for a single translation doc, and print the result'
        label: ClassVar = 'translation'
        backend_class: ClassVar = etl.MongoTranslation

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

    class Base[O: EtlCommandOpts](EtlBaseCommand[O]):
        options_class: ClassVar[type[O]] = EtlCommandOpts

        def setup(self) -> None:
            super().setup()
            self.backend = etl.MongoPipelineLog(context=self.context)

    class List(Base[LogListOpts]):
        'List pipeline logs'
        output_formats: ClassVar[list[str]] = EtlBaseCommand.output_formats + ['table']
        default_format: ClassVar[str] = 'table'
        headers: ClassVar[list[str]] = ['id', 'start', 'states', 'stages', 'runs', 'errors', 'elapsed']
        options_class: ClassVar = LogListOpts

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            arg = parser.add_argument
            arg(
                '--limit', '-l',
                default=10,
                help=f'Results limit, default 10')
            arg(
                '--skip', '-s',
                default=0,
                dest='offset',
                help=f'Skip n results (offset)')
            super().add_arguments(parser)

        async def run(self) -> None:
            kw = dict(limit=self.opts.limit, offset=self.opts.offset)
            srch = self.backend.search({}, **kw)
            results = [
                dict(zip(self.headers, map(x.get_short().get, self.headers)))
                async for x in srch.objs()]
            if self.opts.output == 'table':
                head = dict(zip(self.headers, self.headers))
                body = self.tablulate(results, head)
            else:
                body = dict(results=results)
            self.printobj(body)

    class Show(Base[LogShowOpts]):
        'Show pipeline log'
        options_class: ClassVar = LogShowOpts
        output_formats: ClassVar[list[str]] = EtlBaseCommand.output_formats + ['table']
        summary_fields: ClassVar[dict[LogSummaryMethod, tuple[str, ...]|dict[str, Any]]] = {
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
                choices=list(map(str, LogSummaryMethod)),
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
                nargs='?',
                help='The pipeline log ID, default latest')
            super().add_arguments(parser)

        async def run(self) -> None:
            if self.opts.id:
                log = await self.backend.fetch(self.opts.id)
            else:
                log = await self.backend.fetch_latest()
            try:
                while True:
                    if self.opts.watch and sys.stdout.isatty():
                        os.system('clear')
                    if self.opts.summary:
                        body = getattr(log, self.opts.summary.name)()
                        if self.opts.output == 'table':
                            body = self.output_table(body)
                    else:
                        body = self.default_body(log)
                    self.printobj(body)
                    if log.end or not self.opts.watch:
                        break
                    await asyncio.sleep(self.opts.watch)
                    log = await self.backend.fetch(log.id)
            except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
                pass

        def output_table(self, body: dict) -> str:
            head = self.summary_fields[self.opts.summary]
            if not isinstance(head, Mapping):
                head = dict(zip(head, head))
            if isinstance(body, Mapping):
                body = list(body.items())
            return self.tablulate(body, head)

        def default_body(self, log: PipelineLog) -> dict[str, Any]:
            body = log.model_dump(mode='json', exclude_none=True)
            if not self.opts.verbose:
                body.update(runs=len(body['runs']), states=len(body['states']))
            return body

    class Copy(Base[LogCopyOpts]):
        'Copy pipeline logs to another db'
        options_class: ClassVar = LogCopyOpts

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            parser.add_argument('dest', help='The destination db name')
            super().add_arguments(parser)

        def setup(self) -> None:
            super().setup()
            self.src = self.backend
            self.dst = etl.MongoPipelineLog(
                context={next(iter(self.context)): self.opts.dest})

        async def run(self) -> None:
            src_db = await self.src.db()
            dst_db = await self.dst.db()
            if src_db.name == dst_db.name:
                raise ValueError(f'Source and dest db cannot be the same')
            logger.info(f'Copying from {src_db.name} to {dst_db.name}')
            res = await self.dst.update(self.src.search({}).objs())
            counts = dict(zip(('count', 'created', 'updated'), res))
            self.printobj(counts)

    class Prune(Base[LogPruneOpts]):
        'Prune old pipeline logs'
        options_class: ClassVar = LogPruneOpts

        @classmethod
        def add_arguments(cls, parser: AP) -> None:
            parser.add_argument(
                '--maxage', '-m',
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
