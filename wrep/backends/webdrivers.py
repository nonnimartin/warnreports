from __future__ import annotations

import json
import shutil
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Iterable

from .. import utils

if TYPE_CHECKING:
    from selenium.webdriver import Chrome, ChromeOptions, ChromeService
    from selenium.webdriver.remote.webelement import WebElement
else:
    class Chrome:
        def __new__(cls, *args, **kw):
            from selenium.webdriver import Chrome
            return Chrome(*args, **kw)

    class ChromeOptions:
        def __new__(cls, *args, **kw):
            from selenium.webdriver import ChromeOptions
            return ChromeOptions(*args, **kw)

    class ChromeService:
        def __new__(cls, *args, **kw):
            from selenium.webdriver import ChromeService
            return ChromeService(*args, **kw)

    class WebElement:
        def __new__(cls, *args, **kw):
            from selenium.webdriver.remote.webelement import WebElement
            return WebElement(*args, **kw)

logger = utils.get_logger('backends.webdrivers')

DEFAULT_CHROME_ARGS = (
    '--headless',
    '--no-sandbox',
    '--disable-dev-shm-usage',
    '--disable-gpu',
    '--remote-debugging-pipe',
    '--dns-prefetch-disable')
DEFAULT_CHROME_PREFS = {
    'download.prompt_for_download': False,
    'download.directory_upgrade': True}

@asynccontextmanager
async def selenium(*, args: Iterable[str]|None = None, prefs: dict[str, Any]|None = None, metrics: bool = True, logger: utils.logging.Logger = logger):
    args = tuple(args or ()) + DEFAULT_CHROME_ARGS
    prefs = DEFAULT_CHROME_PREFS|(prefs or {})
    options = ChromeOptions()
    for arg in args:
        options.add_argument(arg)
    options.add_experimental_option('prefs', prefs)
    if metrics:
        options.set_capability('goog:loggingPrefs', dict(performance='INFO'))
    service = ChromeService(executable_path=shutil.which('chromedriver'))
    logger.info(f'Creating selenium webdriver')
    driver = Chrome(service=service, options=options)
    try:
        yield driver
    finally:
        logger.info(f'Quitting selenium webdriver')
        driver.quit()

def getmetrics(driver: Chrome) -> tuple[int, int]:
    reqids = set()
    size = 0
    for log in driver.get_log('performance'):
        message = json.loads(log['message'])['message']
        if message['method'] == 'Network.responseReceived':
            rep = message['params']['response']
            reqids.add(message['params']['requestId'])
            for header in rep['headers']:
                if header.lower() == 'content-length':
                    size += int(rep['headers'][header])
                    break
            else:
                size += rep.get('encodedDataLength', 0)
    return len(reqids), size
