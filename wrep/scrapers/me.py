from __future__ import annotations

import asyncio
from typing import Any, Iterator

from requests.adapters import Retry
from requests.exceptions import ConnectionError, HTTPError

from .base import Scraper

__all__ = ['ME']

class ME(Scraper):

    async def scrape(self) -> None:
        # CSV files appear to get corrupted sometimes, resulting in missing data, which breaks
        # hashing. Clearing the CSV seems to help.
        self.cache.delete('*.csv', glob=True)
        # Quick & dirty retry for ConnectionResetError(104, 'Connection reset by peer')
        retry = Retry(**self.retry)
        while True:
            try:
                self.runner.scrape()
            except (ConnectionError, HTTPError) as err:
                kw = dict(method='GET', error=err)
                try:
                    rep = err.response
                    method = rep.request.method
                    if not retry.is_retry(method, rep.status_code):
                        raise
                    kw.update(response=rep, url=rep.url, method=method)
                except AttributeError:
                    pass
                retry = retry.increment(**kw)
                self.logger.warning(f'{err!r} {retry}')
            else:
                break
            await asyncio.sleep(retry.get_backoff_time())

    def statobjs(self) -> Iterator[Any]:
        yield from self.cache.glob('*.csv')
