from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import sys
from datetime import timedelta
from typing import (TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Mapping,
                    Self)
from uuid import UUID

import yaml
from pydantic import (BeforeValidator, Field, PositiveFloat, field_validator,
                      model_validator)

from .. import settings, utils
from ..models import *
from . import mongo
from .base import AP, AppCommand, AppCommandOpts

if TYPE_CHECKING:
    from ..backends import etl

logger = logging.getLogger(__name__)

class EtlOpts(AppCommandOpts):
    output: Literal['json', 'yaml'] = 'json'
    etl_dbname: str|None = None

class OneOpts(EtlOpts):
    id: UUID = Field(description='The tanslation doc id')
    save: bool = Field(False, description='Save the result')

class TrOneOpts(OneOpts):
    id: UUID = Field(
        description='The extraction doc id, or state & sequence (e.g. WI.123)')

    @field_validator('id', mode='before')
    @classmethod
    def idopt(cls, value: str|Any) -> UUID:
        from ..backends import etl
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

class LogShowOpts(EtlOpts):
    output: Literal['json', 'yaml', 'table'] = 'json'
    summary: LogSummaryMethod|None = Field(
        default=None,
        description=f'The summary type to show')
    verbose: bool = Field(False, description=f'Verbose output')
    id: UUID|None = Field(
        default=None,
        description='The pipeline log ID, default is to fetch latest')
    watch: PositiveFloat|None = Field(
        default=False,
        validate_default=True,
        description='Watch')
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

class LogListOpts(EtlOpts):
    output: Literal['json', 'yaml', 'table'] = 'table'
    limit: Limit = Field(10, description=f'Results limit, default 10')
    offset: Offset = Field(0, description=f'Skip n results (offset)')

class LogCopyOpts(EtlOpts):
    dest: str = Field(description='The destination db name')

class LogPruneOpts(EtlOpts):
    maxage: Annotated[
        timedelta,
        BeforeValidator(utils.deltaopt('days'))] = Field(
            default='30d',
            description='Max age, default 30d',
            validate_default=True)
    dryrun: bool = Field(False, description='Dry run only')

class EtlBaseCommand[O: EtlOpts](AppCommand[O]):
    output_formats: ClassVar[list[str]] = ['json', 'yaml']
    default_format: ClassVar[str] = 'json'
    options_class: ClassVar[type[O]] = EtlOpts

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

class OneBase[O: OneOpts](EtlBaseCommand[O]):
    options_class: ClassVar[type[O]] = OneOpts
    backend: etl.MongoETBase

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        arg = parser.add_argument
        arg('id')
        arg('--save', '-s')
        super().add_arguments(parser)

    async def get_inst(self) -> etl.ETBase:
        srch = self.backend.search(dict(id=self.opts.id), limit=1)
        try:
            return await anext(srch.objs())
        except StopAsyncIteration:
            raise ValueError(f'Doc not found: {self.opts.id}')

class Trone(OneBase[TrOneOpts]):
    'Run translations for a single extraction doc, and print the result'
    options_class: ClassVar = TrOneOpts
    trdumpopts: ClassVar = dict(
        mode='json',
        exclude_unset=True,
        exclude_none=True,
        exclude=['extraction'])

    def setup(self) -> None:
        super().setup()
        from ..backends import etl
        self.backend = etl.MongoExtraction(context=self.context)

    async def run(self) -> None:
        from .. import orm
        from ..backends import etl
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
        from ..backends import etl
        backend = etl.MongoTranslation(context=self.context)
        srch = backend.search(dict(id=self.opts.id), limit=1)
        try:
            translation = await anext(srch.objs())
        except StopAsyncIteration:
            raise ValueError(f'Doc not found: {self.opts.id}')
        self.opts.id = translation.extraction.id
        return await super().get_inst()

class Ldone(OneBase[OneOpts]):
    'Run load operations for a single translation doc, and print the result'

    def setup(self) -> None:
        super().setup()
        from ..backends import etl
        self.backend = etl.MongoTranslation(context=self.context)

    async def run(self) -> None:
        translation: Translation = await self.get_inst()
        # Lazy import for etl requirements separation
        from .. import orm
        from ..pipeline import Pipeline
        with orm.SessionLocal() as session:
            pipeline = Pipeline(
                state=translation.state,
                context=self.context,
                session=session)
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

class LogBase[O: EtlOpts](EtlBaseCommand[O]):
    options_class: ClassVar[type[O]] = EtlOpts

    def setup(self) -> None:
        super().setup()
        from ..backends import etl
        self.backend = etl.MongoPipelineLog(context=self.context)

class LogList(LogBase[LogListOpts]):
    'List pipeline logs'
    output_formats: ClassVar[list[str]] = EtlBaseCommand.output_formats + ['table']
    default_format: ClassVar[str] = 'table'
    headers: ClassVar[list[str]] = ['id', 'start', 'states', 'stages', 'runs', 'errors', 'elapsed']
    options_class: ClassVar = LogListOpts

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        arg = parser.add_argument
        arg('--limit', '-l', default=...)
        arg('--skip', '-s', dest='offset', default=...)
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

class LogShow(LogBase[LogShowOpts]):
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
        arg('--summary', '-s', choices=(...,))
        arg('--verbose', '-v')
        arg('--watch', '-w', nargs='?', metavar='interval', default=...)
        arg('id', nargs='?')
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

class LogCopy(LogBase[LogCopyOpts]):
    'Copy pipeline logs to another db'
    options_class: ClassVar = LogCopyOpts

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        parser.add_argument('dest')
        super().add_arguments(parser)

    def setup(self) -> None:
        super().setup()
        from ..backends import etl
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

class LogPrune(LogBase[LogPruneOpts]):
    'Prune old pipeline logs'
    options_class: ClassVar = LogPruneOpts

    @classmethod
    def add_arguments(cls, parser: AP) -> None:
        parser.add_argument('--maxage', '-m', default=...)
        parser.add_argument('--dryrun')
        super().add_arguments(parser)

    async def run(self) -> None:
        res = await self.backend.prune(self.opts.maxage, dryrun=self.opts.dryrun)
        result = dict(deleted=res)
        if self.opts.dryrun:
            result.update(dryrun=True)
        self.printobj(result)

commands = dict(
    _description='Misc ETL pipeline commands',
    log=dict(
        _description='Pipeline log commands',
        list=LogList,
        show=LogShow,
        copy=LogCopy,
        prune=LogPrune),
    trone=Trone,
    ldone=Ldone,
    control=mongo.makecommands(
        'backends.etl.default_client',
        settings.ETL_MONGODB_DBNAME_KEY))
