from __future__ import annotations

import re
from typing import Callable, Iterable

type Norms = dict[str|re.Pattern, str|Callable[[re.Match], str]]
type SrchSpec = str|re.Pattern|Callable[[str], Iterable[str|re.Pattern]]
type NormDefs = dict[str, SrchSpec|list[SrchSpec]|tuple[SrchSpec, ...]]
_r = re.compile
PAT_NONALPHA = _r(r'[^a-z\d\s]')
PAT_SPACES = _r(r'\s+')

def _sw(s: str) -> Iterable[str|re.Pattern]:
    s = re.escape(s)
    yield _r(r'^'f'{s}'r'.*', re.I)

COMPANY_NAMES: NormDefs = {
    '3M': _sw('3M '),
    '99 Cents Only': _sw,
    'A. O. Smith': [
        _r(r'^a\.\s*o\.\s+smith(\s.*|$)', re.I),
    ],
    'ABM Aviation': _sw,
    'Advance Stores Company': _sw,
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
    'Aramark': [
        _r(r'^Aramark (-|\(|@|at )', re.I),
    ],
    'AT&T': _sw,
    'Avis Budget': _sw,
    'BAE Systems': _sw,
    'Bank of America': _sw,
    'Big Lots': [
        _r(r'^Big Lots(,?\s+.*)?$', re.I),
    ],
    'Boeing': [
        'Boeing Co',
        'Boeing Company',
        'Boeing Compnay',
        'Thte Boeing Company',
        'The Boeing Company',
    ],
    'Carbon Health': [
        'Carbon Health Medical Group',
    ],
    'Caterpillar': _sw,
    'CVS': [
        _r(r'^cvs\s.*', re.I),
    ],
    'Dollar Express': _sw,
    'Enterprise Holdings': _sw,
    'Ericsson Inc': [
        _r(r'^Ericsson,? Inc.*', re.I),
    ],
    'First Student': _sw,
    'G2 Secure Staff': _sw,
    'GDI Services': _sw,
    'Goodwill': [
        _r(r'^Goodwill (Industries| of |Retail|Outlet|Store).*', re.I),
    ],
    'Hard Rock Cafe': [
        _r(r'^Hard Rock (Cafe|Café|International|Hotel).*', re.I),
    ],
    'Hawker Beechcraft': [
        _r(r'^Hawker Beechcraft Corp.*', re.I),
    ],
    'Hostess Brands': [
        _r(r'^Hostess( Brand.*)?$', re.I),
    ],
    'HyAxiom': _sw,
    'Intel Corporation': [
        _r(r'^Intel( Corp.*)?$', re.I),
    ],
    'International Paper': [
        _r(r'^(The )?International Paper.*', re.I),
    ],
    'Jabil': [
        _r(r'^(Nypro .*)?Jabil( .*)$', re.I),
    ],
    'Kaiser Foundation': _sw,
    'Kmart': [
        'KMART CORPORATION',
        'Kmart Store',
    ],
    "Kohl's": _sw,
    'Levi Strauss & Company': [
        _r(r'^.*Levi Strauss & Co.*$'),
    ],
    'Leviton Manufacturing Company': [
        _r(r'^Leviton (Manufacturing|Mfg).*', re.I),
    ],
    'Levy Premium Foodservice': [
        _r(r'^Levy Premium Food\s*service.*', re.I),
    ],
    'Lockheed Martin': _sw,
    'Lord & Taylor': [
        _r(r'^Lord\s*(&|\+|and)\s*(Taylor|Tyalor)(\s.*|$)', re.I),
    ],
    'LSC Communications': _sw,
    'LTF Club Management Company': _sw('LTF Club Management'),
    'ManpowerGroup': _sw,
    'Marvell Semiconductor': _sw,
    'Meta Platforms': _sw,
    'Nordstrom': [
        _r(r'^Nordstrom.*(Anchorage|Center|Inc|Place|Plaza|Rack|Stonestown|Store|Waterside).*', re.I),
        _r(r'^(Dadeland|Lloyd Center)?\s*Nordstrom$', re.I),
    ],
    "P.F. Chang's": [
        _r(r'^P[.\s]*F[.\s]*Chang.*', re.I),
    ],
    'Packers Sanitation Services': _sw('Packers Sanitation'),
    'PepsiCo': _sw,
    'Pitney Bowes': [
        _r(r'^(Newgistics.*)?Pitney Bowes.*', re.I),
    ],
    'Qualcomm': _sw,
    'Radisson Hotel': _sw('Radisson '),
    'Safeway': [
        _r(r'^Safeway(,?\s+Inc.*)?$', re.I),
    ],
    'Sears': [
        _r(r'^Sears.*Roebuck.*', re.I),
    ],
    'Sears Holdings': [
        _r(r'^Sears .*Holdings.*', re.I),
    ],
    'Shaw Industries': _sw,
    'Sikorsky': [
        _r(r'^Sikorsky(,?\s.*)?$', re.I),
    ],
    'Silgan Containers': _sw,
    'Sky Chefs': [
        _r(r'^(LSG.*)?Sky Chefs.*', re.I),
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
    'Sun Microsystems': _sw,
    'SunPower': [
        _r(r'^SunPower( Corp.*)?$', re.I),
    ],
    'Syzygy Plasmonics': _sw('Syzygy'),
    'Symantec': [
        _r(r'^Symantec( -.*|Corp.*)?$', re.I),
    ],
    'T-Mobile': _sw,
    'Tesla': [
        'Tesla Inc',
    ],
    'The Home Depot': [
        _r(r'^(The )?Home Depot.*', re.I),
    ],
    'Transamerica Insurance': _sw('Transamerica Life'),
    'Transdev Services': _sw,
    'True Value': [_sw, 'Ziegler True Value'],
    'Tyson Foods': [
        _r(r'^(Tyson|Keystone) Foods.*', re.I),
    ],
    'United Parcel Service': [
        _sw,
        _r(r'^UPS(,?\s.*)?$'),
    ],
    'United Retail Service': [
        _r(r'^United Retail Service(, LLC)? -.*', re.I),
    ],
    'US Foods': _r(r'^US Foods(,? .*)?$'),
    'Visionworks': _sw,
    'Walgreens': [
        _sw,
        _r(r'^Walgreen (Co|Lab).*', re.I),
    ],
    'Walmart': _sw,
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

def clean(value: str) -> str:
    value_clean = PAT_NONALPHA.sub('', value.lower())
    value_clean = PAT_SPACES.sub(' ', value_clean).strip()
    return value_clean

def _build(norms: Norms, *defs: NormDefs):
    for defn in defs:
        for name, values in defn.items():
            if not isinstance(values, (list, tuple)):
                values = (values,)
            for value in values:
                if callable(value):
                    for value in value(name):
                        norms[value] = name
                else:
                    norms[value] = name
    for key in list(norms):
        if isinstance(key, str):
            norms[clean(key)] = norms[key]

_build(COMPANY_NAME_NORMS, COMPANY_NAMES)

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
