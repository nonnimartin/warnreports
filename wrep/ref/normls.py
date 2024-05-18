from __future__ import annotations

import re
from typing import TypeAlias

Norms: TypeAlias = dict[str|re.Pattern, str]
_r = re.compile

COMPANY_NAME = {
    _r(r'^walmart\s?', re.I): 'Walmart',
    **{value: 'Boeing' for value in [
        'Boeing',
        'Boeing Co',
        'Boeing Company',
        'Boeing Compnay',
        'Thte Boeing Company',
        'The Boeing Company',
    ]},
    **{value: 'Kmart' for value in [
        'KMART CORPORATION',
        'Kmart Store',
    ]},
    **{value: 'Wells Fargo' for value in [
        'WELLS FARGO',
        'Wells Fargo Company',
        'Wells Fargo Co',
        'Wells Fargo and Co',
        'Wells Fargo Company',
    ]},
    'Tesla Inc': 'Tesla',
    'Amazon.com': 'Amazon',
}


def _build(norms: Norms) -> None:
    for key in tuple(norms):
        if isinstance(key, str):
            norms[key.lower()] = norms.pop(key)

_build(COMPANY_NAME)

def apply(norms: Norms, value: str) -> str:
    value_clean = re.sub(r'[^a-z\d\s]', '', value.lower())
    value_clean = re.sub(r'\s+', ' ', value_clean).strip()
    for key in norms:
        if key == value_clean or key == value:
            value_clean = norms[key]
            break
        if isinstance(key, re.Pattern):
            if key.match(value_clean) or key.match(value):
                value_clean = norms[key]
                break
    return value_clean.lower()

def company_name(name: str) -> str:
    return apply(COMPANY_NAME, name)
