from __future__ import annotations

import csv
import json
import logging
import os
import uuid
from argparse import ArgumentParser
from typing import Any

import settings
import utils
import warn.runner
from models import Report, db
from translators import translators


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

    def __init__(self, state: str) -> None:
        self.state = state.upper()
        self.translator = translators[self.state]()
        self.namespace = uuid.uuid5(Report.NAMESPACE, self.state)
        self.dirs = {stage: settings.BUILD_DIR/stage for stage in Stage}
        self.files = dict(
            extract=self.dirs['extract']/f'{state.lower()}.csv',
            translate=self.dirs['translate']/f'{state.lower()}.log')
        self.summary = {}

    def run(self, stage: Stage, clean: bool = False) -> None:
        stage = Stage(stage)
        logging.info(f'run {stage} {self.state}')
        self.summary[stage] = getattr(self, stage)(clean=clean)
        logging.info(f'run {stage} {self.state} {self.summary[stage]}')

    def clean(self, stage: Stage) -> None:
        stage = Stage(stage)
        logging.info(f'clean {stage} {self.state}')
        file = self.files.get(stage)
        if file and os.path.exists(file):
            os.unlink(file)
        if stage is stage.Load:
            Report.delete().where(Report.state == self.state).execute()

    def extract(self, clean: bool = False) -> dict:
        stage = Stage.Extract
        if clean:
            self.clean(stage)
        path = self.dirs[stage]
        scraper = warn.runner.Runner(path, path/'cache')
        scraper.scrape(self.state)
        size = os.stat(self.files[stage]).st_size
        return dict(size=size)

    def translate(self, clean: bool = False) -> dict:
        stage = Stage.Translate
        if clean:
            self.clean(stage)
        utils.makedirs(self.dirs[stage])
        with open(self.files[stage], 'w') as writer:
            count = 0
            it = utils.csvdicts(self.files[stage.Extract])
            for count, row in enumerate(it, start=1):
                entry = dict(id=self.row_uuid(row), row=row)
                entry = self.translator.entry(row) | entry
                json.dump(entry, writer, default=utils.json_default)
                writer.write('\n')
        size = os.stat(self.files[stage]).st_size
        return dict(count=count, size=size)

    def load(self, clean: bool = False) -> dict:
        stage = Stage.Load
        counts = dict.fromkeys(map(str, SaveType), 0)
        with open(self.files[stage.Translate]) as f:
            with db.atomic():
                if clean:
                    self.clean(stage)
                for entry in utils.json_lines(f):
                    action = self.save(entry)
                    counts[action] += 1
                    logging.debug(f'{action} {entry=}')
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

class Stage(utils.StrEnum):
    Extract = 'extract'
    Translate = 'translate'
    Load = 'load'

def main():
    parser = ArgumentParser()
    parser.add_argument('stage', choices=Stage)
    parser.add_argument('states', nargs='*', choices=translators)
    parser.add_argument('--clean', '-c', action='store_true')
    parser.add_argument('--clean-only', '-x', action='store_true')
    opts = parser.parse_args()
    for state in opts.states or translators:
        pipeline = Pipeline(state)
        if opts.clean_only:
            pipeline.clean(opts.stage)
        else:
            pipeline.run(opts.stage, clean=opts.clean)

if __name__ == '__main__':
    utils.init_logging()
    main()
