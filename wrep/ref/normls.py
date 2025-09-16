from __future__ import annotations

import re
from re import compile as r
from typing import Callable, Iterable

type StrPat = str|re.Pattern
type Norms = dict[StrPat, str|Callable[[re.Match], str]]
type SpecFunc = Callable[[str], StrPat|Iterable[StrPat]]
type SrchSpec = StrPat|SpecFunc
type NormDefs = dict[str, SrchSpec|list[SrchSpec]|tuple[SrchSpec, ...]]
PAT_NONALPHA = r(r'[^a-z\d\s]')
PAT_SPACES = r(r'\s+')

def sw(s: str, *strings: str, flags=re.I) -> re.Pattern:
    "Build a 'starts with' case-insensitive pattern"
    strings = (s, *strings)
    return r(f'^({'|'.join(map(re.escape, strings))}).*', flags)

COMPANY_NAMES: NormDefs = {
    '3M': sw('3M '),
    '99 Cents Only': sw,
    'A&B Beverage': sw,
    'A.C. Moore': sw,
    'A. O. Smith': [
        r(r'^a\.\s*o\.\s+smith(\s.*|$)', re.I),
    ],
    'ABM Aviation': sw,
    'ACCO': [
        sw('ACCO', flags=re.NOFLAG),
    ],
    'ADC Telecommunications': sw,
    'ADESA': sw,
    'Advance Stores Company': sw,
    'Advanced Micro Devices': [
        'Advanced Micro Devices (AMD)',
        'Advanced Micro Devices Inc',
        'AMD Inc',
    ],
    'Adventist Health': [
        sw,
        r(r'^.*dba Adventist Health.*', re.I),
    ],
    'Air Wisconsin Airlines': [
        'Air Wisconsin',
    ],
    "Albertson's": [
        r(r'^albertsons.*', re.I),
    ],
    'Alorica': sw,
    'Allied Waste': sw,
    'Alpha Natural Resources': sw,
    'Amazon': [
        sw('Amazon.com'),
        r(r'^Amazon.[A-Z]{3}.*'),
    ],
    'Amentum': [
        sw('Amentum', 'PAE Shared Services'),
    ],
    'Ameri-Kleen': sw,
    "America's Auto Auction": sw,
    'American Apparel': sw,
    'AmeriCold': sw,
    'AmeriHealth': sw,
    'Ames Department Stores': sw,
    'APAC Customer Service': sw,
    'APL Logistics': sw,
    'Applied Materials': sw,
    'Aramark': sw,
    'Aspen Sports': sw,
    'AT&T': sw('AT&T', 'AT & T'),
    'Avis Budget': sw,
    'BAE Systems': sw,
    'Bank of America': sw,
    'BH Security': [
        sw('BH Security', 'Brinks Home'),
    ],
    'Big Lots': [
        r(r'^Big Lots(,?\s+.*)?$', re.I),
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
    'Caterpillar': sw,
    'Chep Services': sw,
    'Cisco Systems': sw('Cisco'),
    'Concentrix': [
        sw('Concentrix', 'Convergys'),
    ],
    'Constellis': [
        sw('Centerra', 'Constellis', 'Triple Canopy'),
    ],
    'CVS': [
        r(r'^cvs\s.*', re.I),
    ],
    'Danimer Scientific': sw,
    'DHL': [
        r(r'^.*DHL.*'),
    ],
    'Dish Network': sw,
    'Dollar Express': sw,
    'Eastman Kodak': sw,
    'Enterprise Holdings': sw,
    'Ericsson Inc': [
        r(r'^Ericsson,? Inc.*', re.I),
    ],
    'Federal Express': [
        sw('Federal Express', 'FedEx'),
    ],
    'First Student': sw,
    'First Transit': sw,
    'Forever 21': [
        sw('Forever 21', 'F21'),
    ],
    'G2 Secure Staff': sw,
    'GCA Education Services': [
        r(r'^(ABM/)?GCA Education.*$', re.I),
    ],
    'GDI Services': sw,
    'Goodwill': [
        r(r'^Goodwill (Industries| of |Retail|Outlet|Store).*', re.I),
    ],
    'GXO Logistics': sw,
    'Hard Rock Cafe': [
        r(r'^Hard Rock (Cafe|Café|International|Hotel).*', re.I),
    ],
    'Hawker Beechcraft': [
        r(r'^Hawker Beechcraft Corp.*', re.I),
    ],
    'HMS Host': sw,
    'Hostess Brands': [
        r(r'^Hostess( Brand.*)?$', re.I),
    ],
    'HyAxiom': sw,
    'IG Design Group': sw,
    'Intel Corporation': [
        r(r'^Intel( Corp.*)?$', re.I),
    ],
    'International Paper': [
        r(r'^(The )?International Paper.*', re.I),
    ],
    'Jabil': [
        r(r'^(Nypro .*)?Jabil( .*)?$', re.I),
    ],
    'Jack Cooper': sw,
    'J.B. Hunt': sw,
    'JCPenney': [
        r(r'^.*JCPenney.*$', re.I),
    ],
    'JP Morgan Chase': sw('JP Morgan Chase', 'JPMorgan Chase'),
    'John Deere': sw,
    'Hormel Foods': [
        r(r'^(.*subsidiary.*)?Hormel Foods.*', re.I),
    ],
    'Kaiser Foundation': sw,
    'Kmart': [
        'KMART CORPORATION',
        'Kmart Store',
    ],
    "Kohl's": sw,
    'LEGOLAND': sw,
    'Levi Strauss & Company': [
        r(r'^.*Levi Strauss & Co.*$'),
    ],
    'Leviton Manufacturing Company': [
        r(r'^Leviton (Manufacturing|Mfg).*', re.I),
    ],
    'Levy Premium Foodservice': [
        r(r'^Levy Premium Food\s*service.*', re.I),
    ],
    'Lockheed Martin': [
        r(r'^Lockheed (Martin|Aeronautical).*', re.I),
    ],
    'LogRhythm': sw,
    'Lord & Taylor': [
        r(r'^Lord\s*(&|\+|and)\s*(Taylor|Tyalor)(\s.*|$)', re.I),
    ],
    'LSC Communications': sw,
    'LTF Club Management Company': sw('LTF Club Management'),
    "Macy's Systems": sw,
    "Macy's": sw,
    'ManpowerGroup': sw,
    'Marvell Semiconductor': sw,
    'Merck': sw,
    'Meta Platforms': sw,
    'Microsoft': sw,
    'MVM': sw,
    'NeueHouse': sw,
    'New York Life Insurance': sw('New York Life'),
    'Nordstrom': [
        r(r'^Nordstrom.*(Anchorage|Center|Inc|Place|Plaza|Rack|Stonestown|Store|Waterside).*', re.I),
        r(r'^(Dadeland|Lloyd Center)?\s*Nordstrom$', re.I),
    ],
    'Novartis Pharmaceuticals': sw,
    'Owens Corning': sw,
    "P.F. Chang's": [
        r(r'^P[.\s]*F[.\s]*Chang.*', re.I),
    ],
    'Packers Sanitation Services': sw('Packers Sanitation'),
    'Penske Logistics': sw,
    'PepsiCo': sw,
    'Perdue Foods': sw,
    'Pfizer': sw,
    'Pioneer Hi-Bred': sw,
    'Pitney Bowes': [
        r(r'^(Newgistics.*)?Pitney Bowes.*', re.I),
    ],
    'Providence Health': sw,
    'Qualcomm': sw,
    'Radisson Hotel': sw('Radisson '),
    'Ryder': sw,
    'Safeway': [
        r(r'^Safeway(,?\s+(Inc|Store).*)?$', re.I),
    ],
    'Salesforce': sw,
    'Sears': [
        r(r'^Sears.*Roebuck.*', re.I),
    ],
    'Sears Holdings': [
        r(r'^Sears .*Holdings.*', re.I),
    ],
    'Shaw Industries': sw,
    'Sherwood Food Distributors': [
        sw,
        r(r'^Harvest (Sherwood|Meat).*', re.I),
    ],
    'Sikorsky': [
        r(r'^Sikorsky(,?\s.*)?$', re.I),
    ],
    'Silgan Containers': sw,
    'Six Flags Entertainment': sw('Six Flags'),
    'Sky Chefs': [
        r(r'^(LSG.*)?Sky Chefs.*', re.I),
    ],
    'Sodexo': [
        r(r'^Sodexo(,?\s+Inc.*)?$', re.I),
    ],
    'Solo Cup': [
        'Solo Cup Company',
        'Solo Cup Operating Corporation',
    ],
    'Southwest Airlines': [
        sw('Southwest - Dallas'),
    ],
    'Sprint': sw,
    'Staples': [
        'Staples the Office Superstore LLC',
        'Staples Inc',
    ],
    'State Farm Insurance': [
        r(r'^state farm mutual.* insurance.*', re.I),
    ],
    'Sun Microsystems': sw,
    'SunPower': [
        r(r'^SunPower( Corp.*)?$', re.I),
    ],
    'Syzygy Plasmonics': sw('Syzygy'),
    'Symantec': [
        r(r'^Symantec( -.*|Corp.*)?$', re.I),
    ],
    'T-Mobile': sw,
    'Telluride Sports': sw,
    'Tesla': [
        'Tesla Inc',
    ],
    'The Home Depot': [
        sw('The Home Depot', 'Home Depot'),
    ],
    'The North Face': sw,
    'Thermo Fisher Scientific': sw('Thermo Fisher'),
    'TouchPoint Support Services': sw,
    'Transamerica Insurance': sw('Transamerica Life'),
    'Transdev Services': sw,
    'True Value': [
        sw,
        'Ziegler True Value',
    ],
    'Tyson Foods': [
        r(r'^(Tyson|Keystone) Food.*', re.I),
    ],
    'United Parcel Service': [
        sw,
        r(r'^UPS(,?\s.*)?$'),
    ],
    'United Retail Service': [
        sw,
        'Urs-united Retail Service',
    ],
    'US Foods': r(r'^US Foods(,? .*)?$'),
    'Virginia Mason': sw,
    'Visionworks': sw,
    'Walgreens': [
        sw('Walgreens', 'Walgreen Co', 'Walgreen Lab'),
    ],
    'Walmart': sw,
    'Wells Fargo': sw,
    # 'Wells Fargo': [
    #     'Wells Fargo Company',
    #     'Wells Fargo Co',
    #     'Wells Fargo and Co',
    #     'Wells Fargo Company',
    # ],
    'Yellow Corporation': [
        r(r'^Yellow (Corp|Freight|Transportation|Trucking).*', re.I),
        r(r'^YRC .*Freight.*', re.I),
    ],
    'Zillow Group': sw('Zillow'),
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
    r(r'^('f'{'|'.join(AIRLINE_COMPANIES)}'r') airlines.*', re.I):
        lambda m: f'{m.group(1).title()} Airlines',
    r(r'^('f'{'|'.join(INSURANCE_COMPANIES)}'r')( insurance.*)?$', re.I):
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
                    value = value(name)
                if isinstance(value, (str, re.Pattern)):
                    value = (value,)
                for value in value:
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
