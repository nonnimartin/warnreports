from __future__ import annotations

import re
from typing import Callable, TypeAlias

Norms: TypeAlias = dict[str|re.Pattern, str|Callable[[re.Match], str]]
_r = re.compile

_airlines = [
    'united',
    'alaska',
    'american',
    'american eagle',
    'southwest',
    'delta',
    'hawaiian',
    'northwest',
    'spirit',
    'air wisconsin',
    'el al israeli',
    'frontier',
    'pinnacle',
    'piedmont',
]
_insurance = [
    'allstate',
    'state farm',
    'liberty mutual',
    'new york life',
    'nationwide',
    'farmers',
    'transamerica',
    'trinity universal',
]
COMPANY_NAME: Norms = {
    _r(r'^walmart.*', re.I): 'Walmart',
    _r(r'^99 cents only.*', re.I): '99 Cents Only',
    _r(r'^3M .*', re.I): '3M',
    _r(r'^at&t.*', re.I): 'AT&T',
    _r(r'^('f'{'|'.join(_airlines)}'r') airlines.*', re.I):
        lambda m: f'{m.group(1).title()} Airlines',
    _r(r'^('f'{'|'.join(_insurance)}'r') insurance.*', re.I):
        lambda m: f'{m.group(1).title()} Insurance',
    _r(r'^state farm mutual.* insurance.*', re.I): 'State Farm Insurance',
    _r(r'^albertsons.*', re.I): "Albertson's",
    _r(r'^cvs\s.*', re.I): 'CVS',
    _r(r'^abm aviation.*', re.I): 'ABM Aviation',
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

PAT_NONALPHA = _r(r'[^a-z\d\s]')
PAT_SPACES = _r(r'\s+')

def clean(value: str) -> str:
    value_clean = PAT_NONALPHA.sub('', value.lower())
    value_clean = PAT_SPACES.sub(' ', value_clean).strip()
    return value_clean

def _build(norms: Norms):
    for key in list(norms):
        if isinstance(key, str):
            norms[clean(key)] = norms[key]

_build(COMPANY_NAME)

def norm(norms: Norms, value: str) -> str:
    value_clean = clean(value)
    for key in norms:
        if key == value_clean or key == value:
            value_norm = norms[key]
            break
        if isinstance(key, re.Pattern):
            if key.match(value):
                value_norm = key.sub(norms[key], value)
                break
            if key.match(value_clean):
                value_norm = key.sub(norms[key], value_clean)
                break
    else:
        value_norm = value_clean
    return clean(value_norm)

def canon(norms: Norms, value: str) -> str:
    if value in norms:
        return norms[value]
    value_clean = clean(value)
    if value_clean in norms:
        return norms[value_clean]
    for key in norms:
        if isinstance(key, re.Pattern):
            if key.match(value):
                return key.sub(norms[key], value)
            if key.match(value_clean):
                return key.sub(norms[key], value_clean)
    return value

def company_name_norm(name: str) -> str:
    return norm(COMPANY_NAME, name)

def company_name_canon(name: str) -> str:
    return canon(COMPANY_NAME, name)
