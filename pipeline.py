from __future__ import annotations

import csv
import json
import logging
import os
from argparse import ArgumentParser
from datetime import datetime
from typing import Any

import fixed
import settings
import utils
import warn.runner
from models import Company, Report, db


class Translator:

    state: str
    registry = {}
    datetime_fields = {'reported', 'starting'}

    def __new__(cls, state: str):
        return super().__new__(cls.registry.get(state.upper(), cls))

    def __init__(self, state: str):
        self.state = state.upper()

    def entry(self, row: list[str], headers: list[str]) -> dict[str, Any]:
        'Translate a source row to an entry'
        entry = {}
        for header, value in zip(headers, row):
            field = self.field(header)
            if not field:
                continue
            entry[field] = self.value(field, value)
        return entry

    def field(self, header: str) -> str|None:
        'Translate a source header to a field name'
        return fixed.conversions[self.state].get(header)

    def value(self, field: str, value: str) -> Any:
        'Translate a field value'
        method = f'value_{field}'
        if hasattr(self, method):
            return getattr(self, method)(value)
        return self.value_default(field, value)

    def value_company(self, value: str) -> str:
        return value.split('\n')[0].strip()

    def value_action(self, value: str) -> str:
        return value.strip('*').strip()

    value_employees = staticmethod(utils.parse_int)

    def value_default(self, field: str, value: str) -> str|datetime:
        value = value.strip()
        if field in self.datetime_fields:
            value = utils.parse_date(value)
        return value

    def from_json(self, field: str, value: Any) -> Any:
        if field in self.datetime_fields:
            value = utils.parse_date(value)
        return value

    @classmethod
    def register(cls, state: str, subcls: type[Translator]|None = None):
        def decorate(subcls: type[Translator]):
            cls.registry[state.upper()] = subcls
            return subcls
        return decorate(subcls) if subcls else decorate

@Translator.register('CT')
class TransCT(Translator):

    def value_reported(self, value: str) -> datetime|None:
        for value in value.split(' '):
            value = utils.parse_date(value)
            if value:
                return value

class Pipeline:

    stages = ['extract', 'translate', 'load']
    fields = [
        'company',
        'state',
        'location',
        'reported',
        'starting',
        'employees',
        'action']
    required_fields = [
        'company',
        'state',
        'reported']

    def __init__(self, state: str) -> None:
        self.state = state.upper()
        self.dirs = {
            stage: settings.PIPELINE_DIR/stage
            for stage in self.stages}
        self.translator = Translator(self.state)
        self.files = dict(
            scrape=self.dirs['extract']/f'{state.lower()}.csv',
            entries=self.dirs['translate']/f'{state.lower()}.json')

    def extract(self) -> dict:
        path = self.dirs['extract']
        scraper = warn.runner.Runner(path, path/'cache')
        scraper.scrape(self.state)
        size = os.stat(self.files['scrape']).st_size
        return dict(size=f'{size:,}')

    def translate(self) -> dict:
        entries = []
        utils.makedirs(self.dirs['translate'])
        with open(self.files['scrape']) as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                logging.warning(f'Empty csv')
            for row in reader:
                entry = self.translator.entry(row, headers)
                entry.update(state=self.state, row=row)
                entries.append(entry)
        with open(self.files['entries'], 'w') as f:
            json.dump(entries, f, indent=2, default=utils.json_default)
        return dict(entries=len(entries))

    def load(self) -> dict:
        with open(self.files['entries']) as f:
            entries = json.load(f)
        created = 0
        skipped = 0
        with db.atomic():
            for entry in entries:
                try:
                    created += self.load_entry(entry)
                except SkipEntry:
                    skipped += 1
                    logging.debug(f'Skipping {entry=}')
        return dict(read=len(entries), created=created, skipped=skipped)

    def load_entry(self, entry: dict) -> int:
        record = {
            field: self.translator.from_json(field, entry[field])
            for field in self.fields if field in entry}
        if not all(map(record.get, self.required_fields)):
            raise SkipEntry
        count = 0
        company, created = Company.get_or_create(
            name=record.pop('company'),
            state=record.pop('state'))
        count += created
        if created:
            logging.debug(f'Created {company=}')
        report, created = Report.get_or_create(company=company, **record)
        count += created
        if created:
            logging.debug(f'Created {report=}')
        return count

class SkipEntry(Exception):
    pass

def main():
    parser = ArgumentParser()
    parser.add_argument('stage', choices=Pipeline.stages)
    parser.add_argument('states', nargs='*', choices=fixed.states)
    opts = parser.parse_args()
    stage = opts.stage
    states = opts.states or fixed.states
    for state in states:
        logging.info(f'{stage=} {state=}')
        pipeline = Pipeline(state)
        summary = getattr(pipeline, opts.stage)()
        logging.info(f'{stage=} {state=} {summary=}')

if __name__ == '__main__':
    utils.init_logging()
    main()
