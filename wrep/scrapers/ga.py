from __future__ import annotations

import asyncio
import csv
import json
import re
from contextlib import contextmanager
from itertools import chain
from typing import Any, ClassVar, Iterable, Iterator
from urllib.parse import parse_qs, urlparse

import requests.exceptions

from ..tools import strs, dom, asyn
from .base import Scraper

__all__ = ['GA']

class GA(Scraper):
    base_url: ClassVar = 'https://www.tcsg.edu'
    latest_url: ClassVar = '/warn-public-view/'
    request_delay: ClassVar = 1.0
    api_url: ClassVar = f'/wp-admin/admin-ajax.php'
    user_agent: ClassVar = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36')
    extra_headers: ClassVar = ['entry_url', 'submitted_date', 'artifacts_json']

    async def scrape(self) -> None:
        await self.download('latest.html', self.latest_url)
        payload = dict(self.payload, nonce=self.extract_nonce())
        async def getbody():
            return (await self.session.arequest('POST', self.api_url, data=payload)).json()
        wait = asyn.Wait(timeout=20, poll=2, ignored=requests.exceptions.JSONDecodeError)
        try:
            body = await wait.until(getbody)
        except TimeoutError as err:
            raise err.__cause__ or err
        self.cache.write_json('latest.json', body, indent=2)
        index = self.build_index()
        if self.needs_scrape():
            await asyncio.sleep(0)
            await self.runner.scrape()
        artifacts = {}
        for notice_id in index:
            infos = dict(self.extract_artifact_infos(notice_id))
            if infos:
                artifacts[notice_id] = infos
        self.cache.write_json('artifacts.json', artifacts, indent=2)
        it = chain.from_iterable(map(dict.items, artifacts.values()))
        for key, url in it:
            await self.download(key, url, missing_only=True)
            self.artifacts.add(key)

    async def clean(self) -> None:
        await super().clean()
        self.cache.delete('*.format3', glob=True)

    def statobjs(self) -> Iterator[Any]:
        yield from sorted(self.cache.glob('*.json'))
        yield from sorted(self.cache.glob('*.format3'), reverse=True)

    def build_index(self) -> dict[str, tuple[str, str]]:
        body: dict = self.cache.read_json('latest.json')
        index: dict[str, tuple[str, str]] = {}
        for listing in body['data']:
            a = dom.bs(listing[0], 'html5lib').find('a')
            notice_id = a.text
            url = self.absurl(a['href'])
            datestr = listing[2]
            index[notice_id] = (url, datestr)
        self.cache.write_json('index.json', index, indent=2)
        return index

    def needs_scrape(self) -> bool:
        index = self.cache.read_json('index.json')
        source = self.runner.file
        keys = (f'{key}.format3' for key in index)
        return not (
            source.exists() and
            source.stat().st_size and
            self.cache.exists('index.json') and
            all(map(self.cache.exists, keys)))

    def extract_artifact_infos(self, notice_id: str) -> Iterator[tuple[str, str]]:
        doc = dom.bs(self.cache/f'{notice_id}.format3')
        for a in doc.find_all('a', {'data-type': 'pdf'}):
            filename = self.artifact_filename(a['href'])
            if filename:
                cachekey = f'records/{notice_id}-{filename}'
                yield cachekey, self.absurl(a['href'])

    def extract_nonce(self) -> str|None:
        doc = dom.bs(self.cache/'latest.html', 'html5lib')
        script = doc.find(
            'script',
            text=lambda text: text and 'window.gvDTglobals.push' in text)
        match = re.search(r'"nonce":"([^"]+)"', str(script))
        if match:
            return match.group(1)

    def artifact_filename(self, href: str) -> str|None:
        vals = parse_qs(urlparse(href).query).get('gf-download')
        if vals and vals[0].endswith('.pdf'):
            return strs.clean_filename(vals[0])

    payload: ClassVar = dict(
        columns=[
            dict(data=i, name=name, searchable=True, orderable=True, search={})
            for i, name in enumerate(['gv_96', 'gv_4', 'gv_date_created', 'gv_97'])],
        order=[dict(column=0, dir='asc')],
        draw=1,
        start=0,
        length=-1,
        search={},
        action='gv_datatables_data',
        view_id=77460,
        post_id=77462,
        getData=[],
        hideUntilSearched=0,
        setUrlOnSearch=True,
        shortcode_atts=dict(id=77460))

    @contextmanager
    def extract(self):
        index: dict = self.cache.read_json('index.json')
        artifacts = self.cache.read_json('artifacts.json')
        todo = set(artifacts)

        def readrecords(it: Iterable[list[str]]):
            headers = next(it) + self.extra_headers
            fillrow = [''] * len(self.extra_headers)
            for values in it:
                idkey = values[0]
                fill = list(fillrow)
                if idkey in index:
                    fill[:2] = index[idkey]
                if idkey in artifacts:
                    fill[2] = json.dumps(artifacts[idkey])
                    todo.discard(idkey)
                values.extend(fill)
                yield dict(zip(headers, values))

        with self.runner.file.open() as file:
            yield readrecords(csv.reader(file))
        for idkey in todo:
            self.logger.warning(f'Unassociated artifact {idkey}')
