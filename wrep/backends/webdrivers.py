from __future__ import annotations

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

@asynccontextmanager
async def selenium(*, args: Iterable[str]|None = None, prefs: dict[str, Any]|None = None):
    args = tuple(args or ()) + DEFAULT_CHROME_ARGS
    options = ChromeOptions()
    for arg in args:
        options.add_argument(arg)
    if prefs:
        options.add_experimental_option('prefs', prefs)
    service = ChromeService(executable_path=shutil.which('chromedriver'))
    logger.info(f'Creating selenium webdriver')
    driver = Chrome(service=service, options=options)
    try:
        yield driver
    finally:
        logger.info(f'Quitting selenium webdriver')
        driver.quit()
