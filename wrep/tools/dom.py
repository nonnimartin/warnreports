from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from bs4 import BeautifulSoup as Soup
from bs4.element import PageElement, ResultSet, Tag


def bs(markup: Any, features='html.parser', **kw):
    if isinstance(markup, Path):
        markup = markup.read_bytes()
    return Soup(markup, features, **kw)

if TYPE_CHECKING:
    from typing import overload
    class Soup(Soup):
        @overload
        def find_all(
            self,
            name:str|Any=...,
            attrs: dict[str, Any]=...,
            recursive:bool=True,
            string:str|Any=...,
            limit:int|None=...,
            **kwargs) -> ResultSet[Soup|PageElement|Tag]: ...
