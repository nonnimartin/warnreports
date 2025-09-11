from __future__ import annotations

from collections import abc
from itertools import chain
from typing import TYPE_CHECKING, ClassVar, Iterable

from . import utils, settings
from .models import StateCode, ValidStateCode

if TYPE_CHECKING:
    from ._scrapers.base import Scraper as ScraperType
else:
    type ScraperType = type

DEFAULT_PATH = [f'{__package__}._scrapers']

class ScraperRegistry(abc.MutableMapping[StateCode, type[ScraperType]]):
    __slots__ = ['path', *abc.MutableMapping.__abstractmethods__]
    logger: ClassVar = utils.get_logger('scrapers.registry')
    path: list[str]
    'Package/module search path'

    def __init__(self, *, path: Iterable[str]|None = None) -> None:
        if path is None:
            self.path = list(DEFAULT_PATH)
        elif isinstance(path, str):
            self.path = [path]
        else:
            self.path = list(path)
        mapping = {}
        for name in ('__delitem__', '__iter__', '__len__'):
            setattr(self, name, getattr(mapping, name))

        def setitem(key, value):
            try:
                state = ValidStateCode(key)
            except ValueError:
                raise KeyError(key)
            try:
                from ._scrapers.base import Scraper
                if not issubclass(value, Scraper):
                    raise ValueError(value)
            except TypeError:
                raise ValueError(value)
            mapping[state] = value

        def getitem(key):
            try:
                return mapping[key]
            except KeyError:
                pass
            try:
                return self.load(key)
            except ValueError:
                raise KeyError(key)

        self.__getitem__ = getitem
        self.__setitem__ = setitem

    def load(self, state: StateCode) -> type[ScraperType]:
        state = ValidStateCode(state)
        it = ((path, f'{path}.{state.lower()}') for path in self.path)
        from importlib import import_module
        from ._scrapers.base import Scraper
        for cand in chain.from_iterable(it):
            try:
                mod = import_module(cand)
                value = getattr(mod, state)
            except (ModuleNotFoundError, AttributeError):
                continue
            try:
                if issubclass(value, Scraper):
                    break
            except TypeError:
                continue
        else:
            if (settings.REPODIR/f'warn/scrapers/{state.lower()}.py').exists():
                value = type(state, (Scraper,), {})
            else:
                raise ValueError(f'Cannot load Scraper {state=} path={self.path}')
        self[state] = value
        return value

registry = ScraperRegistry()
'Scraper class registry'
