from __future__ import annotations

import re
from typing import Callable

type Norms = dict[str|re.Pattern, str|Callable[[re.Match], str]]
_r = re.compile
PAT_NONALPHA = _r(r'[^a-z\d\s]')
PAT_SPACES = _r(r'\s+')

COMPANY_NAMES = {
    '3M': [
        _r(r'^3M .*', re.I),
    ],
    '99 Cents Only': [
        _r(r'^99 cents only.*', re.I),
    ],
    'A. O. Smith': [
        _r(r'^a\.\s*o\.\s+smith(\s.*|$)', re.I),
    ],
    'ABM Aviation': [
        _r(r'^abm aviation.*', re.I),
    ],
    'Advanced Micro Devices': [
        'Advanced Micro Devices (AMD)',
        'Advanced Micro Devices Inc',
        'AMD Inc',
    ],
    "Albertson's": [
        _r(r'^albertsons.*', re.I),
    ],
    'Amazon': [
        'Amazon.com',
    ],
    'AT&T': [
        _r(r'^at&t.*', re.I),
    ],
    'Boeing': [
        'Boeing Co',
        'Boeing Company',
        'Boeing Compnay',
        'Thte Boeing Company',
        'The Boeing Company',
    ],
    'CVS': [
        _r(r'^cvs\s.*', re.I),
    ],
    'Kmart': [
        'KMART CORPORATION',
        'Kmart Store',
    ],
    'Levi Strauss & Company': [
        _r(r'^.*Levi Strauss & Co.*$'),
    ],
    'Leviton Manufacturing Company': [
        _r(r'^Leviton (Manufacturing|Mfg).*', re.I),
    ],
    'Levy Premium Foodservice': [
        _r(r'^Levy Premium Food\s*service.*', re.I),
    ],
    'Lockheed Martin': [
        _r(r'^Lockheed Martin.*$', re.I),
    ],
    'Lord & Taylor': [
        _r(r'^Lord\s*(&|\+|and)\s*(Taylor|Tyalor)(\s.*|$)', re.I),
    ],
    'LSC Communications': [
        _r(r'^LSC Communications.*', re.I),
    ],
    'LTF Club Management Company': [
        _r(r'^LTF Club Management.*', re.I),
    ],
    'Radisson Hotel': [
        _r(r'^Radisson .*', re.I),
    ],
    'Sears': [
        _r(r'^Sears.*Roebuck.*', re.I),
    ],
    'Sears Holdings': [
        _r(r'^Sears .*Holdings.*', re.I),
    ],
    'Shaw Industries': [
        _r(r'^Shaw Industries.*', re.I),
    ],
    'Sikorsky': [
        _r(r'^Sikorsky(,?\s.*)?$', re.I),
    ],
    'Sodexo': [
        _r(r'^Sodexo(,?\s+Inc.*)?$', re.I),
    ],
    'Solo Cup': [
        'Solo Cup Company',
        'Solo Cup Operating Corporation',
    ],
    'Staples': [
        'Staples the Office Superstore LLC',
        'Staples Inc',
    ],
    'State Farm Insurance': [
        _r(r'^state farm mutual.* insurance.*', re.I),
    ],
    'Sun Microsystems': [
        _r(r'^Sun Microsystems.*', re.I),
    ],
    'SunPower': [
        _r(r'^SunPower( Corp.*)?$', re.I),
    ],
    'Tesla': [
        'Tesla Inc',
    ],
    'United Parcel Service': [
        _r(r'^United Parcel Service.*', re.I),
        _r(r'^UPS(,?\s.*)?$'),
    ],
    'United Retail Service': [
        _r(r'^United Retail Service(, LLC)? -.*', re.I),
    ],
    'Walmart': [
        _r(r'^walmart.*', re.I),
    ],
    'Wells Fargo': [
        'Wells Fargo Company',
        'Wells Fargo Co',
        'Wells Fargo and Co',
        'Wells Fargo Company',
    ],
    'Yellow Corporation': [
        _r(r'^Yellow (Corp|Freight|Transportation|Trucking).*', re.I),
        _r(r'^YRC .*Freight.*', re.I),
    ],
}
AIRLINE_COMPANIES = [
    'United',
    'Alaska',
    'American',
    'American Eagle',
    'Southwest',
    'Delta',
    'Hawaiian',
    'Northwest',
    'Spirit',
    'Air Wisconsin',
    'El Al Israeli',
    'Frontier',
    'Pinnacle',
    'Piedmont',
]
INSURANCE_COMPANIES = [
    'Allstate',
    'State Farm',
    'Liberty Mutual',
    'New York Life',
    'Nationwide',
    'Farmers',
    'Transamerica',
    'Trinity Universal',
]

COMPANY_NAME_NORMS: Norms = {
    _r(r'^('f'{'|'.join(AIRLINE_COMPANIES)}'r') airlines.*', re.I):
        lambda m: f'{m.group(1).title()} Airlines',
    _r(r'^('f'{'|'.join(INSURANCE_COMPANIES)}'r')( insurance.*)?$', re.I):
        lambda m: f'{m.group(1).title()} Insurance',
}

COMPANY_NAME_NORMS.update(
    (value, name)
    for name, values in COMPANY_NAMES.items()
    for value in values)

def clean(value: str) -> str:
    value_clean = PAT_NONALPHA.sub('', value.lower())
    value_clean = PAT_SPACES.sub(' ', value_clean).strip()
    return value_clean

def _build(norms: Norms):
    for key in list(norms):
        if isinstance(key, str):
            norms[clean(key)] = norms[key]

_build(COMPANY_NAME_NORMS)

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
    return norm(COMPANY_NAME_NORMS, name)

def company_name_canon(name: str) -> str:
    return canon(COMPANY_NAME_NORMS, name)

def company_name_sort(name: str) -> tuple[bool, bool, bool, int, str]:
    return (
        name != name.title(),
        name == name.lower(),
        name == name.upper(),
        len(name),
        name)
