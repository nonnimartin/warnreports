from __future__ import annotations

import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo.operations import IndexModel

from . import search, settings, utils
from .models import *
from .models import db
from .scrapers import scrapers
from .translators import translators
from .utils import Stage

logger = utils.get_logger('pipeline')

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
        self.mongo = search.mongo if settings.MONGODB_ENABLED else None
        self.summary = {}

    async def run(self, stage: Stage, clean: bool = False) -> None:
        stage = Stage(stage)
        logger.info(f'run {stage} {self.state}')
        self.summary[stage] = await getattr(self, stage)(clean=clean)
        logger.info(f'run {stage} {self.state} {self.summary[stage]}')

    async def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'clean {stage} {self.state}')
        if stage is stage.Load:
            Report.delete().where(Report.state == self.state).execute()
        elif stage is stage.Index:
            if self.mongo is None:
                raise Exception(f'mongo not enabled')
            await self.mongo.reports.delete_many(dict(state=self.state))
        elif stage is stage.Extract:
            self.scraper.clean()
        else:
            if self.mongo is None:
                self.file(stage).unlink(missing_ok=True)
            else:
                await self.mongo.translations.delete_many(dict(state=self.state))

    async def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        file = self.scraper.file
        hashes = dict(prev=utils.hashfile(file, missing_ok=True))
        if clean:
            await self.clean(stage)
        self.scraper.scrape()
        hashes.update(cur=utils.hashfile(file))
        change = len(set(hashes.values())) > 1
        size = file.stat().st_size
        return dict(change=change, size=size, hashes=hashes)

    async def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        if clean:
            await self.clean(stage)
        async with self.ctx_translate() as (reader, writer):
            count = 0
            async for row in reader:
                count += 1
                entry = self.translator.entry(row)
                entry.update(id=self.entry_uuid(entry, row), state=self.state, row=row)
                await writer.write(entry)
        return dict(count=count)

    async def load(self, clean: bool = False) -> dict:
        stage = Stage.Load
        counts = dict.fromkeys(map(str, SaveType), 0)
        async with self.ctx_load() as reader:
            if clean:
                await self.clean(stage)
            async for entry in reader:
                counts[self.save(entry)] += 1
        counts['total'] = sum(counts.values())
        return counts

    async def index(self, clean: bool = False) -> dict:
        stage = Stage.Index
        if self.mongo is None:
            raise Exception(f'mongo not enabled')
        if clean:
            await self.clean(stage)
        q = Report.select_for_reduce()
        q = q.where(Report.state == self.state)
        docs = map(ReportData.as_doc, ReportData.map_reduce(q))
        count = q.count()
        counts = dict(created=0, updated=0)
        if clean:
            if count:
                await self.mongo.reports.insert_many(docs, ordered=False)
                counts['created'] += count
        else:
            for doc in docs:
                filt = dict(_id=doc['_id'])
                res = await self.mongo.reports.replace_one(filt, doc, True)
                counts['updated'] += res.modified_count
        return counts

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

    def file(self, stage: Stage) -> Path|None:
        return Stage(stage).file(self.state)

    def entry_uuid(self, entry: dict[str, Any], row: dict[str, str]) -> uuid.UUID:
        src = entry.get('report_id') or json.dumps(list(row.values()))
        return uuid.uuid5(self.namespace, src)

    def from_json(self, field: str, value: Any) -> Any:
        if field in self.json_types:
            if isinstance(value, str):
                value = self.json_types[field](value)
        return value

    @asynccontextmanager
    async def ctx_translate(self):
        with utils.csvdicts(self.scraper.file, restkey='__') as reader:
            reader = utils.as_aiter(reader)
            if self.mongo is None:
                dest = self.file(Stage.Translate)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('w') as file:
                    yield reader, LogdictWriter(file)
            else:
                yield reader, MongoWriter(self.mongo.translations)
                await self.mongo.translations.create_indexes([
                    IndexModel({'id': 'hashed'})])

    @asynccontextmanager
    async def ctx_load(self):
        if self.mongo is None:
            with utils.logdicts(self.file(Stage.Translate)) as reader:
                with db.atomic():
                    yield utils.as_aiter(reader)
        else:
            with db.atomic():
                yield self.mongo.translations.find(dict(state=self.state))

class EntryWriter:
    async def write(self, entry: dict[str, Any]):
        raise NotImplementedError

class LogdictWriter(EntryWriter):

    def __init__(self, file: io.TextIOWrapper):
        self.file = file

    async def write(self, entry: dict[str, Any]):
        json.dump(entry, self.file, default=utils.json_default)
        self.file.write('\n')

class MongoWriter(EntryWriter):

    def __init__(self, coll: AsyncIOMotorCollection):
        self.coll = coll

    async def write(self, entry: dict[str, Any]):
        await self.coll.replace_one(dict(id=entry['id']), entry, True)

class SaveType(utils.StrEnum):
    Create = 'create'
    Update = 'update'
    Nochange = 'nochange'
    Skip = 'skip'

class Command(utils.BaseCommand):
    'Run a pipeline stage'

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument('stage', choices=Stage)
        parser.add_argument('states', nargs='*', choices=translators)
        parser.add_argument('--clean', '-c', action='store_true')
        parser.add_argument('--clean-only', '-x', action='store_true')

    async def run(self):
        opts = self.opts
        for state in opts.states or translators:
            pipeline = Pipeline(state)
            if opts.clean_only:
                await pipeline.clean(opts.stage)
            else:
                await pipeline.run(opts.stage, clean=opts.clean)

if __name__ == '__main__':
    Command.main()
