from __future__ import annotations

import re
from html import unescape as unhtml
from re import compile as _r
from typing import Callable, Iterable
from uuid import UUID, uuid5

from .. import settings

__all__ = [
    'absurl',
    'clean_filename',
    'rewrite_all',
    'struuid',
    'unhtml']

type SrchRepl = tuple[str|re.Pattern, str|Callable[[re.Match], str]]
STRNS = uuid5(settings.NAMESPACE, 'tools.strs')

clean_filename_subs = [
    (_r(r'[^a-z\d_]', re.I), '-'),
    (_r(r'([-_])+'), r'\1'),
]
clean_extension_subs = [(rw[0], '') for rw in clean_filename_subs]


def absurl(base_url: str|None, url: str) -> None:
    if base_url and not url.startswith(('http://', 'https://')):
        url = base_url.rstrip('/') + '/' + url.lstrip('/')
    return url

def clean_filename[T](
        value: str,
        default: T = None,
        # Return string without extension
        stem: bool = False,
        # Raise on empty result
        fail: bool = False) -> str|T:
    parts = value.rsplit('.', not stem)
    clean = rewrite_all(parts[0], clean_filename_subs)
    clean = clean.strip('_-')
    if clean:
        if len(parts) == 2:
            ext = rewrite_all(parts[1], clean_extension_subs)
            clean = f'{clean}.{ext}'
        return clean
    if fail and not default:
        raise ValueError(f'Empty clean filename {value=}')
    return default

def rewrite_all(value: str, rewrites: Iterable[SrchRepl]) -> str:
    for srch, repl in rewrites:
        if srch == value:
            value = repl
        elif isinstance(srch, re.Pattern):
            value = srch.sub(repl, value)
    return value

def struuid(value: str) -> UUID:
    return uuid5(STRNS, value)