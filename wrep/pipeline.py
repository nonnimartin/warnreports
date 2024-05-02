from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import warn.runner

from . import utils
from .models import Report, State, db
from .settings import BUILD_DIR
from .translators import translators

logger = utils.get_logger('pipeline')

class Stage(utils.StrEnum):
    Extract = 'extract'
    Translate = 'translate'
    Load = 'load'

    @property
    def dir(self) -> Path:
        return BUILD_DIR/self

    @property
    def fileext(self) -> str|None:
        if self is self.Extract:
            return 'csv'
        if self is self.Translate:
            return 'log'

    def file(self, state: State) -> Path|None:
        if self.fileext:
            return Path(self.dir, f'{state.lower()}.{self.fileext}')


class Pipeline:

    fields = [
        'id',
        'company',
        'location',
        'reported',
        'starting',
        'employees',
        'action',
        'url']
    required_fields = {'company', 'reported'}
    json_types = {
        'id': uuid.UUID,
        'reported': utils.parse_date,
        'starting': utils.parse_date}

    def __init__(self, state: State) -> None:
        self.state = state.upper()
        self.translator = translators[self.state]()
        self.namespace = uuid.uuid5(Report.NAMESPACE, self.state)
        self.summary = {}

    def run(self, stage: Stage, clean: bool = False) -> None:
        stage = Stage(stage)
        logger.info(f'run {stage} {self.state}')
        self.summary[stage] = getattr(self, stage)(clean=clean)
        logger.info(f'run {stage} {self.state} {self.summary[stage]}')

    def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logger.info(f'clean {stage} {self.state}')
        if stage is stage.Load:
            Report.delete().where(Report.state == self.state).execute()
        else:
            self.file(stage).unlink(missing_ok=True)

    def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        if clean:
            self.clean(stage)
        file = self.file(stage)
        parent = file.parent
        scraper = warn.runner.Runner(parent, parent/'cache')
        scraper.scrape(self.state)
        return dict(size=file.stat().st_size)

    def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        if clean:
            self.clean(stage)
        file = self.file(stage)
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open('w') as writer:
            count = 0
            it = utils.csvdicts(self.file(stage.Extract))
            for count, row in enumerate(it, start=1):
                entry = dict(id=self.row_uuid(row), row=row)
                entry = self.translator.entry(row) | entry
                json.dump(entry, writer, default=utils.json_default)
                writer.write('\n')
        return dict(count=count, size=file.stat().st_size)

    def load(self, clean: bool = False) -> dict:
        stage = Stage.Load
        counts = dict.fromkeys(map(str, SaveType), 0)
        it = utils.logdicts(self.file(stage.Translate))
        with db.atomic():
            if clean:
                self.clean(stage)
            for entry in it:
                counts[self.save(entry)] += 1
        return counts | dict(total=sum(counts.values()))

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
        for field, value in record.items():
            if save is save.Create or getattr(report, field) != value:
                setattr(report, field, value)
        if save is save.Nochange and report.dirty_fields:
            save = save.Update
        if save is not save.Nochange:
            report.save(force_insert=save is save.Create)
        return save

    def file(self, stage: Stage) -> Path|None:
        return Stage(stage).file(self.state)

    def row_uuid(self, row: dict[str, str]) -> uuid.UUID:
        return uuid.uuid5(self.namespace, json.dumps(list(row.values())))

    def from_json(self, field: str, value: Any) -> Any:
        if field in self.json_types:
            value = self.json_types[field](value)
        return value

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

    def run(self):
        opts = self.opts
        for state in opts.states or translators:
            pipeline = Pipeline(state)
            if opts.clean_only:
                pipeline.clean(opts.stage)
            else:
                pipeline.run(opts.stage, clean=opts.clean)

if __name__ == '__main__':
    Command.main()
