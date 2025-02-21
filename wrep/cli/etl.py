from __future__ import annotations

import json
from typing import Any, ClassVar, Mapping
from uuid import UUID

import yaml

from .. import orm, utils
from ..backends import etl, mongo
from ..backends.mongo import Search, filters
from ..models import *
from ..pipeline import Pipeline
from ..translators import translators
from .base import AP, AppCommand, BaseCommand
from .mongo import ClientControlCommand

logger = utils.get_logger('etl')

class EtlBaseCommand(AppCommand):

    @classmethod
    def add_arguments(cls, parser: AP):
        arg = parser.add_argument
        arg('--etl-dbname', '-b',
            default=None,
            help=f'Alternate mongo etl db name')
        super().add_arguments(parser)

    def setup(self, opts):
        super().setup(opts)
        self.context = {etl.client.dbname_key: opts.etl_dbname}

class OneCommand(BaseCommand):

    class Base(EtlBaseCommand):
        label: ClassVar[str] = '?'
        collection: ClassVar[mongo.MongoCollection]

        @classmethod
        def add_arguments(cls, parser: AP):
            parser.add_argument('--save', '-s', action='store_true', help='Save the result')
            parser.add_argument('--yaml', action='store_true', help='Output yaml')
            parser.add_argument('id', type=UUID, help=f'The {cls.label} doc id')
            super().add_arguments(parser)

        def printobj(self, obj: Any) -> None:
            print(self.objtext(obj))

        def objtext(self, obj: Any) -> str:
            if self.opts.yaml:
                text = yaml.safe_dump(obj, sort_keys=False)
            else:
                text = json.dumps(obj, indent=2)
            return text

        def get_filter(self):
            return filters[self.collection.data_model](id=[self.opts.id])

        async def get_inst(self):
            res = Search(self.get_filter(), limit=1, context=self.context)
            try:
                return await anext(res.objs())
            except StopAsyncIteration:
                raise ValueError(f'Doc not found: {self.opts.id}')

    class Trone(Base):
        'Run translations for a single extraction doc, and print the result'
        label = 'extraction'
        collection = etl.MongoExtraction.collection

        async def run(self):
            inst: Extraction = await self.get_inst()
            objs = list(translators[inst.state]().translate(inst.model_extra))
            docs = [
                x.model_dump(mode='json', exclude_unset=True, exclude_none=True)
                for x in objs]
            self.printobj(docs)
            if self.opts.save:
                backend = etl.MongoTranslation(inst.state, context=self.context)
                await backend.update(objs)

        async def get_inst(self):
            try:
                return await super().get_inst()
            except ValueError as err:
                logger.warning(f'Extraction {self.opts.id} not found, checking translations')
            filter = filters[Translation](id=[self.opts.id])
            res = Search(filter, limit=1, context=self.context)
            try:
                translation = await anext(res.objs())
            except StopAsyncIteration:
                raise ValueError(f'Doc not found: {self.opts.id}')
            self.opts.id = translation.row.id
            return await super().get_inst()

    class Ldone(Base):
        'Run load operations for a single translation doc, and print the result'
        label = 'translation'
        collection = etl.MongoTranslation.collection

        async def run(self):
            inst: Translation = await self.get_inst()
            pipeline = Pipeline(inst.state, context=self.context)
            with orm.SessionLocal() as session:
                pipeline.session = session
                pipeline.artifact_cache = {}
                report, save = pipeline.save(inst)
                if report is not None:
                    row = (report, report, None, None)
                    report, = orm.Report.map_reduce([row])
                    report = report.model_dump(mode='json', exclude_unset=True)
                self.printobj(dict(save=save, report=report))
                if self.opts.save and save is not save.Nochange:
                    session.commit()
                else:
                    session.rollback()

    commands = dict(trone=Trone, ldone=Ldone)

class LogCommand(BaseCommand):
    'Pipeline log commands'

    class Show(EtlBaseCommand):
        'Show pipeline log'

        summary_methods: ClassVar[dict[str, str]] = {
            'short': 'get_short',
            'runs': 'get_runs',
            'load-changes': 'get_load_changes',
            'scrape-stats': 'get_scrape_stats'}
        summary_fields: ClassVar[dict[str, tuple[str, ...]|dict[str, Any]]] = {
            'short': dict(key=0, value=1),
            'runs': ('stage', 'state', 'elapsed', 'failed', 'nochange'),
            'load-changes': ('state', 'created', 'updated'),
            'scrape-stats': ('state', 'elapsed')}

        @classmethod
        def add_arguments(cls, parser):
            arg = parser.add_argument
            arg(
                '--summary', '-s',
                choices=cls.summary_methods,
                default=None,
                help=(f'The summary type to show'))
            arg(
                '--output', '-o',
                choices=['json', 'yaml', 'table'],
                help=f'Output format')
            arg(
                '--tablefmt',
                default='simple',
                help=f'Table format')
            arg(
                'id',
                type=UUID,
                nargs='?',
                default=None,
                help='The pipeline log ID, default latest')
            super().add_arguments(parser)

        def setup(self, opts):
            super().setup(opts)
            self.summary: str|None = self.opts.summary
            self.output: str = self.opts.output
            if not self.summary and self.output == 'table':
                self.parser.error(f'Table output only supported with summary')
            self.backend = etl.MongoPipelineLog(context=self.context)

        async def run(self):
            if self.opts.id:
                log = await self.backend.fetch(self.opts.id)
            else:
                log = await self.backend.fetch_latest()
            if self.summary:
                body = getattr(log, self.summary_methods[self.summary])()
            else:
                body = self.default_body(log)
            if self.output == 'table':
                text = self.output_table(body)
            elif self.output == 'yaml':
                text = yaml.safe_dump(body, sort_keys=False)
            else:
                text = json.dumps(body, indent=2)
            print(text)

        def output_table(self, body: dict) -> str:
            head = self.summary_fields[self.summary]
            if not isinstance(head, Mapping):
                head = dict(zip(head, head))
            if isinstance(body, Mapping):
                body = list(body.items())
            from tabulate import tabulate
            return tabulate(body, head, tablefmt=self.opts.tablefmt, floatfmt='.2f')

        def default_body(self, log: PipelineLog) -> dict:
            body = log.model_dump(mode='json')
            body['runs'] = len(body['runs'])
            body['states'] = len(body['states'])
            return body

    class Copy(EtlBaseCommand):
        'Copy pipeline logs to another db'

        @classmethod
        def add_arguments(cls, parser):
            parser.add_argument('dest', help='The destination db name')
            super().add_arguments(parser)

        def setup(self, opts):
            super().setup(opts)
            self.src = etl.MongoPipelineLog(context=self.context)
            self.dst = etl.MongoPipelineLog(context={next(iter(self.context)): opts.dest})

        async def run(self):
            src_db = await self.src.db()
            dst_db = await self.dst.db()
            if src_db.name == dst_db.name:
                raise ValueError(f'Source and dest db cannot be the same')
            logger.info(f'Copying from {src_db.name} to {dst_db.name}')
            res = await self.dst.update(await self.src.findall())
            counts = dict(zip(('count', 'created', 'updated'), res))
            print(counts)

    class Prune(EtlBaseCommand):
        'Prune old pipeline logs'

        @classmethod
        def add_arguments(cls, parser):
            parser.add_argument(
                '--maxage', '-m',
                type=utils.deltaopt('days'),
                default='30d',
                help='Max age, default 30d')
            super().add_arguments(parser)

        def setup(self, opts):
            super().setup(opts)
            self.backend = etl.MongoPipelineLog(context=self.context)

        async def run(self):
            res = await self.backend.prune(self.opts.maxage)
            counts = dict(deleted=res)
            print(counts)

    commands = dict(show=Show, copy=Copy, prune=Prune)

class Command(BaseCommand):
    'Misc ETL pipeline commands'
    commands = dict(
        log=LogCommand,
        **OneCommand.commands,
        control=ClientControlCommand(etl.client))
