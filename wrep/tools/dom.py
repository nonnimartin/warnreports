from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

# bs4 is an etl-only requirement, so allow for missing module and fail at runtime.
try:
    from bs4 import BeautifulSoup as SoupBase
    from bs4.element import PageElement, ResultSet, Tag
except ModuleNotFoundError as err:
    if TYPE_CHECKING:
        raise
    class SoupBase:
        import_error = err
        def __new__(cls, *args, **kw):
            raise cls.import_error
    PageElement = ResultSet = Tag = SoupBase

if TYPE_CHECKING:
    from typing import overload
    class Soup(SoupBase):
        @overload
        def find_all(
            self,
            name:str|Any=...,
            attrs: dict[str, Any]=...,
            recursive:bool=True,
            string:str|Any=...,
            limit:int|None=...,
            **kwargs) -> ResultSet[SoupFindType]: ...
        @overload
        def find(
            self,
            name:str|Any=...,
            attrs: dict[str, Any]=...,
            recursive:bool=True,
            string:str|Any=...,
            **kwargs) -> SoupFindType|None: ...
        @overload
        def __getattr__(self, tag: str) -> SoupFindType: ...
else:
    Soup = SoupBase

type SoupFindType = Soup|PageElement|Tag

def bs(markup: Any, features='html.parser', **kw):
    if isinstance(markup, Path):
        markup = markup.read_bytes()
    return Soup(markup, features, **kw)