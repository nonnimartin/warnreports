from __future__ import annotations

import csv
import json
import logging
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import fixed
import settings
import utils
import warn.runner
from models import Company, Report, db


class FieldsMixin:
    state: str
    fields = [
        'company',
        'state',
        'location',
        'reported',
        'starting',
        'employees',
        'action']
    required_fields = {
        'company',
        'state',
        'reported'}
    datetime_fields = {
        'reported',
        'starting'}

class Translator(FieldsMixin):

    registry = {}

    def __new__(cls, state: str):
        return super().__new__(cls.registry.get(state.upper(), cls))

    def __init__(self, state: str):
        self.state = state.upper()

    def entry(self, row: list[str], headers: list[str]) -> dict[str, Any]:
        'Translate a source row to an entry'
        entry = dict.fromkeys(self.fields)
        entry.update(state=self.state, row=row)
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
        'Translate'
        if field == 'action':
            value = value.strip('*')
        value = value.strip()
        if field == 'company':
            value = value.split('\n')[0].strip()
        elif field == 'employees':
            value = utils.get_int(value)
        elif field in self.datetime_fields:
            value = utils.get_date(value)
        return value

    @classmethod
    def register(self, cls: type[Translator], state: str|None = None):
        state = (state or cls.state).upper()
        self.registry[state] = cls
        return cls

class Pipeline(FieldsMixin):

    STAGES = ['extract', 'translate', 'load']

    def __init__(self, state: str) -> None:
        self.state = state.upper()
        self.csvfile = settings.WARN_DATA_DIR + '/' + state.lower() + '.csv'
        self.repfile = settings.REPORTS_DIR + '/' + state.lower() + '.json'
        self.translator = Translator(self.state)
        self.scraper = warn.runner.Runner(
            Path(settings.WARN_DATA_DIR),
            Path(settings.WARN_CACHE_DIR))

    def extract(self) -> None:
        self.scraper.scrape(self.state)

    def translate(self) -> None:
        results = []
        utils.makedirs(settings.REPORTS_DIR)
        with open(self.csvfile) as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                pass
            for row in reader:
                entry = self.translator.entry(row, headers)
                results.append(entry)
        with open(self.repfile, 'w') as f:
            json.dump(results, f, indent=2, default=utils.json_default)

    def load(self) -> None:
        with open(self.repfile) as f:
            results: list[dict] = json.load(f)
        with db.atomic():
            for entry in results:
                if not all(map(entry.get, self.required_fields)):
                    logging.warning(f'Skipping {entry=}')
                    continue
                for field in self.datetime_fields:
                    entry[field] = utils.get_date(entry[field])
                company, created = Company.get_or_create(
                    name=entry.pop('company'),
                    state=entry.pop('state'))
                if created:
                    logging.info(f'Created {company=}')
                entry.pop('row', None)
                report, created = Report.get_or_create(company=company, **entry)
                if created:
                    logging.info(f'Created {report=}')

parser = ArgumentParser()
parser.add_argument('--stage', '-s', choices=Pipeline.STAGES)
parser.add_argument('states', nargs='*', choices=fixed.states)

def main():
    opts = parser.parse_args()
    stages = [opts.stage] if opts.stage else Pipeline.STAGES
    states = opts.states or fixed.states
    for state in states:
        pipeline = Pipeline(state)
        for stage in stages:
            logging.info(f'{stage}:{state}')
            getattr(pipeline, stage)()

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
