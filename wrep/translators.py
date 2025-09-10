from __future__ import annotations

import dataclasses
import inspect
import json
import re
import uuid
from datetime import datetime
from html import unescape as html_unescape
from pathlib import Path
from re import compile as _r
from types import MappingProxyType as MapProxy
from typing import Any, Callable, ClassVar, Iterable, Mapping

from pydantic import HttpUrl

from . import orm, utils
from .models import *
from .orm import ReportMod
from .ref.dt import MONTHNAME_REWRITES
from .ref.tz import zoneinfos
from .tools import strs

PAT_NONALPHANUM = _r(r'[^a-z0-9]+', re.I)
PAT_NONDIGITS = _r(r'[^\d]+')
PAT_NAICSSPLIT = _r(r'[\s,:/]+')
PAT_DATESTRCLEAN = _r(r'[^\d\s/-]')
ASCII_TRANS = {
    0x0009: ' ',
    0x0080: ' ',
    0x0093: '',
    0x0095: ' ',
    0x00a0: ' ',
    0x200b: '',
    0x2013: '-',
    0x2019: "'",
    0x201c: '"',
    0x201d: '"',
}

logger = utils.get_logger('translators')

@dataclasses.dataclass
class TranslateInfo:
    data: Mapping[str, str]
    memo: dict = dataclasses.field(default_factory=dict)

def varcall[T](func: Callable[..., T], *args) -> T:
    return func(*args[:len(inspect.signature(func).parameters)])

@dataclasses.dataclass
class TranslationFactory:
    session: orm.Session
    translators: ClassVar[dict[StateCode, type[Translator]]] = {}

    def translate(self, extraction: Extraction|Any) -> Iterable[Translation]:
        extraction: Extraction = Extraction.model_validate(extraction)
        translator = self.translators[extraction.state]()
        # Remove nulls
        data = MapProxy({
            key: value for key, value in extraction.data.items()
            if value is not None})
        for data in translator.individuate(data):
            data = MapProxy(dict(data))
            inst = Translation(
                state=extraction.state,
                values_id=self.values_id(translator, data),
                extraction=extraction)
            # Sanitize
            info = TranslateInfo(MapProxy({
                key: self.sanitize(value) for key, value in data.items()}))
            try:
                varcall(translator.prepare, inst, info)
                self.populate(translator, inst, info)
                varcall(translator.finish, inst, info)
                self.finalize(translator, inst, info)
                yield Translation.model_validate(inst)
            except:
                logger.error(f'{inst}')
                raise

    def values_id(self, translator: Translator, data: Mapping[str, str|None]) -> uuid.UUID:
        base = dict(data)
        for key in translator.values_hash_exclude:
            base.pop(key, None)
        # Backwards-compatibility
        if '__' in base:
            base['__'] = json.loads(base['__'])
        sourcestr = json.dumps(list(base.values()))
        return uuid.uuid5(translator.ns, sourcestr)

    def sanitize(self, value: str) -> str:
        return value.translate(ASCII_TRANS).strip()

    def populate(self, translator: Translator, inst: Translation, info: TranslateInfo) -> None:
        for field, headers in translator.fieldsmap.items():
            if getattr(inst, field) is not None:
                continue
            for header in headers:
                value = info.data.get(header)
                if value is None:
                    continue
                value = self.value(translator, field, value, info)
                if value is not None and value != '':
                    setattr(inst, field, value)
                    break

    def value(self, translator: Translator, field: str, value: str, info: TranslateInfo) -> Any:
        'Translate a field value'
        if field in translator.rewrites:
            value = strs.rewrite_all(value, translator.rewrites[field])
        method = f'value_{field}'
        if (func := getattr(translator, method, None)):
            value = varcall(func, value, info)
        return value

    def finalize(self, translator: Translator, inst: Translation, info: TranslateInfo) -> None:
        inst.url = inst.url or translator.default_url
        if inst.report_id:
            self.extend_report_id(translator, inst)
            inst.id = uuid.uuid5(translator.ns, inst.report_id)
        else:
            inst.id = inst.values_id
        self.fill_mod(translator, inst, info)

    def extend_report_id(self, translator: Translator, inst: Translation) -> None:
        parts = [inst.report_id]
        for field in translator.report_id_extra:
            value = getattr(inst, field)
            if value is None:
                pass
            elif isinstance(value, datetime):
                parts.append(value.strftime(f'%Y-%m-%d'))
            elif isinstance(value, int):
                parts.append(str(value))
            elif isinstance(value, str):
                parts.append(PAT_NONALPHANUM.sub('', value).upper())
            else:
                raise ValueError(f'Cannot extend report_id with {field=} {value=}')
        inst.report_id = '_'.join(parts)

    def fill_mod(self, translator: Translator, inst: Translation, info: TranslateInfo) -> None:
        if not (scrape_time := utils.parse_date(info.data.get('scrape_time'))):
            return
        stmt = orm.select(ReportMod).where(ReportMod.id == inst.id)
        repmod = self.session.scalar(stmt)
        if not repmod:
            repmod = ReportMod(id=inst.id, ns=translator.ns)
        if not repmod.first_scraped or scrape_time < repmod.first_scraped:
            repmod.first_scraped = scrape_time
            self.session.add(repmod)
        inst.first_scraped = repmod.first_scraped
        if inst.reported and repmod.first_scraped < inst.reported:
            inst.reported = repmod.first_scraped.replace(
                tzinfo=translator.tz)
            offset = inst.reported.utcoffset()
            if offset:
                inst.reported += offset
            inst.reported = inst.reported.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0)

class Translator:
    fieldsmap: ClassVar[Mapping[str, list[str]]] = dict(
        company=[],
        reported=[],
        location=[],
        employees=[],
        starting=[],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    default_url: ClassVar[str|None] = None
    values_hash_exclude: ClassVar[list[str]] = []
    report_id_extra: ClassVar[list[str]] = []
    rewrites: ClassVar[dict[str, list[strs.SrchRepl]]] = dict(
        employees=[
            (_r(r'(\d),(\d)'), r'\1\2'), # remove comma separators
            (_r(r'\d{1,2}/\d{1,2}/\d{2,4}'), ''), # remove dates M/D/Y
            (_r(r'\d{1,2}/\d{2,4}'), ''), # remove dates M/Y
            (_r(r'\d{4}-\d{2}-\d{2}'), ''), # remove dates YYYY-MM-DD
        ])

    def individuate(self, data: Mapping[str, str]) -> Iterable[Mapping[str, str]]:
        """
        Break up extraction data into multiple variants for translation, if needed.
        """
        yield data

    def prepare(self, inst: Translation) -> None:
        pass

    def finish(self, inst: Translation) -> None:
        pass

    def value_reported(self, value: str) -> datetime|None:
        return max(self.parse_dates(value), default=None)

    def value_starting(self, value: str) -> datetime|None:
        return min(self.parse_dates(value), default=None)

    def value_employees(self, value: str) -> int|None:
        num = utils.parse_int(value)
        if num is not None:
            return num
        it = map(utils.parse_int, PAT_NONDIGITS.split(value))
        return max(filter(None, it), default=None)

    def value_company(self, value: str) -> str:
        value = ' '.join(value.split())
        value = value.strip()
        return value

    def value_action(self, value: str) -> str:
        return value

    def value_location(self, value: str) -> str:
        return value

    def value_url(self, value: str) -> HttpUrl|None:
        try:
            return HttpUrl(value)
        except ValidationError:
            pass

    def value_naics(self, value: str) -> list[int]:
        values = set()
        for value in PAT_NAICSSPLIT.split(value):
            if value in ('31-33', '44-45', '48-49'):
                minmax = list(map(int, value.split('-')))
                values.update(range(minmax[0], minmax[1] + 1))
                continue
            value = utils.parse_int(value)
            if value and 2 <= len(str(value)) <= 6:
                values.add(value)
        return sorted(values)

    def value_artifacts(self, value: str) -> dict[str, HttpUrl]:
        try:
            data = dict(json.loads(value))
        except json.JSONDecodeError:
            if value.endswith('.pdf') or value.endswith('.xlsx'):
                data = {Path(value).name: value}
            else:
                data = {}
        artifacts = {}
        for path, url in data.items():
            path = path.strip('/')
            try:
                url = HttpUrl(url)
                Path(path)
            except ValueError:
                continue
            artifacts[path] = url
        return artifacts

    def parse_date(self, value: str) -> datetime|None:
        dt = utils.parse_date(value)
        if dt and (
            # If we parsed a time, something likely went wrong.
            not any((dt.hour, dt.minute, dt.second)) and
            # Sane date range
            1980 <= dt.year <= utils.now().year + 10):
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=self.tz)
            return dt

    def parse_dates(self, value: str) -> list[datetime]:
        return list(map(self.parse_date, self.parseable_date_strings(value)))

    def parseable_date_strings(self, value: str) -> Iterable[str]:
        if self.parse_date(value):
            yield value
            return
        # For cases like TN:
        #   June 12, 2023 - August 11, 2023
        v2 = strs.rewrite_all(value, MONTHNAME_REWRITES)
        if v2 != value:
            # Only try this strategy if we matched a month name
            if len(parts := value.split(' - ')) > 1:
                it = list(filter(self.parse_date, parts))
                if it:
                    yield from it
        else:
            # Fallback strategy
            value = PAT_DATESTRCLEAN.sub(' ', value).strip(' /-')
            yield from filter(self.parse_date, value.split())

    def __init_subclass__(cls) -> None:
        cls.rewrites = Translator.rewrites | cls.rewrites
        cls.values_hash_exclude = sorted({
            'artifacts_json',
            'row_key',
            *cls.values_hash_exclude,
            *Extraction.stat_exclude_fields})
        if len(state := cls.__name__.upper()) == 2:
            cls.state = state
            cls.tz = zoneinfos[cls.state]
            cls.ns = uuid.uuid5(ReportData.NS, state)
            TranslationFactory.translators[state] = cls

# 1/1/2000-1/2/2000 -> 1/1/2000 - 1/2/2000
REWRITE_COMPACT_DATERANGE = (_r(r'(/\d+)-(\d+/)'), r'\1 - \2')

# // -> /
REWRITE_DOUBLE_SLASH = (_r('//'), '/')

REWRITE_UNESCAPE_HTML = (_r(r'.*'), lambda m: html_unescape(m[0]))

class AK(Translator):
    default_url = 'https://jobs.alaska.gov/RR/WARN_notices.htm'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date'],
        location=['Location'],
        employees=['Employees Affected'],
        starting=['Layoff Date'],
        action=['Notes'],
        url=[],
        industry=[],
        report_id=['url'],
        naics=[],
        artifacts=['artifacts_json'])
    rewrites = dict(
        starting=[
            ('June-August 2023', '2023-06-01'),
            ('August-November 2021', '2021-08-01'),
            ('March to May 2016', '2016-03-01'),
        ],
        report_id=[
            (_r(r'^https://.*/notices/([^/]+)$'), r'\1'),
        ]
    )

class AL(Translator):
    default_url = 'https://www.madeinalabama.com/warn-list/'
    fieldsmap = dict(
        company=['Company'],
        reported=['Initial Report Date'],
        location=['City'],
        employees=['Planned # of Affected Employees'],
        starting=['Planned Starting Date'],
        action=['Closing or Layoff'],
        url=[],
        industry=[],
        report_id=['record_number'],
        naics=[],
        artifacts=[])
    rewrites = dict(
        action=[
            (_r(r'\s*\*$'), ''),
        ]
    )

class AZ(Translator):
    default_url = 'https://www.azjobconnection.gov/search/warn_lookups/new'
    fieldsmap = dict(
        company=['employer'],
        reported=['notice_date'],
        location=['city'],
        employees=['number_of_employees_affected'],
        starting=['notice_date'],
        action=['warn_type'],
        url=['detail_page_url'],
        industry=[],
        report_id=['detail_page_url'],
        naics=[],
        artifacts=[])
    rewrites = dict(
        report_id=[
            (_r(r'^https://.+/(\d+)$'), r'\1'),
        ]
    )

class CA(Translator):
    default_url = 'https://edd.ca.gov/en/Jobs_and_Training/Layoff_Services_WARN'
    fieldsmap = dict(
        company=['company'],
        reported=['notice_date'],
        location=['address'],
        employees=['num_employees'],
        starting=['effective_date'],
        action=['layoff_or_closure'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=['artifacts_json'])
    rewrites = dict(
        company=[
            REWRITE_UNESCAPE_HTML,
            (_r(r'\*'), ''),
            (_r(r'\n'), ' '),
            (_r(r',$'), ''),
            (_r(r'Bar- ?B- ?Que\.?'), 'Bar-B-Que'),
            (_r(r'^Abercrombe'), 'Abercrombie'),
        ],
        starting=[
            ('03/30/3030', '2020-03-30'),
            ('03/09/2121', '2021-03-09'),
        ],
        location=[
            (_r(r'\s{2,}'), ', '),
        ],
    )

class CO(Translator):
    default_url = 'https://cdle.colorado.gov/employers/layoff-separations/layoff-warn-list'
    fieldsmap = dict(
        company=['company'],
        reported=['received_date', 'notice_date'],
        location=['city', 'location'],
        employees=['jobs'],
        starting=['begin_date'],
        action=['reason'],
        url=[],
        industry=['naics'],
        report_id=[],
        naics=['naics'],
        artifacts=['artifacts_json'])
    rewrites = dict(
        reported=[
            REWRITE_COMPACT_DATERANGE,
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('4/3020', '2020-04-30'),
            ('4/6', ''),
        ],
        naics=[
            (_r(r'-[-\s]'), r' '),
            (_r(r'^(\d+), (\d+:)'), r'\1\2'),
        ],
        industry=[
            (_r(r'^[\d\s,]+: (.*)$'), r'\1'),
            (_r(r'Practioners'), 'Practitioners'),
        ],
        location=[
            (_r(r'^\d+$'), ''),
        ],
    )

class CT(Translator):
    base_url = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'
    default_url = f'{base_url}/warnreports.htm'
    fieldsmap = dict(
        company=['affected_company'],
        reported=['warn_date'],
        location=['layoff_location'],
        employees=['number_workers'],
        starting=['layoff_date'],
        action=['closing'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=['artifacts_json'])
    rewrites = dict(
        company=[
            (_r(r'\*'), ''),
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('3rd Quarter 2015-4th Quarter 2016', '2015-07-01'),
            ('June 2017 - March 2018', '2017-06-01'),
            ('First quarter 2019 - 2020', '2019-01-01'),
            ('June 2018 - September 2, 2018', '2018-06-01'),
            ('Beginning June 2018', '2018-06-01'),
            ('December 2018 - March 1, 2019', '2018-12-01'),
            ('Reduction in Hours Since March 2020', '2020-03-01'),
            ('April-June 2020', '2020-04-01'),
            ('3/16 - 12/13/2020', '2020-03-16'),
            ('February - March 2023', '2023-02-01'),
        ],
        location=[
            ('Not Indicated', ''),
            ('CT', ''),
        ],
        action=[
            (_r(r'^Yes.*'), 'Closing'),
        ]
    )
    urlfmt = '{}/warn{}.htm'

    def finish(self, inst):
        if not inst.url and inst.reported:
            year = inst.reported.year
            if year >= 2015:
                inst.url = self.urlfmt.format(self.base_url, year)

class DC(Translator):
    base_url = 'https://does.dc.gov'
    default_url = f'{base_url}/page/rapid-response'
    fieldsmap = dict(
        company=['Organization Name'],
        reported=['Notice Date'],
        location=[],
        employees=['Number toEmployees Affected'],
        starting=['Effective Layoff Date'],
        action=['Code Type'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        reported=[
            ('May 2 and 5, 2020', '2020-05-05'),
            ('May 7,14 & 31, 2012', '2012-05-31'),
            ('31, 2019', '2019-10-31'),
        ],
        starting=[
            ('February 28, 2022 March 31, 2022', '2022-02-28'),
            ('December 3 - December 17, 2022', '2022-12-03'),
            ('November 15 - December 16, 2022', '2022-11-15'),
            ('December 25, and Feb - Jun 2021', '2020-12-25'),
            ('September 15, 2020 and March 18, 2020', '2020-03-18'),
            ('June 23,2013', '2013-06-23'),
            ('May 31, 2012 June 15, 2012', '2012-05-31'),
            ('June 29, 2012 & August 3, 2012', '2012-06-29'),
        ],
        action=[
            ('1', 'Layoff'),
            ('2', 'Permanent Closure'),
        ],
    )
    urlfmt = '{}/page/industry-closings-and-layoffs-warn-notifications-{}'

    def finish(self, inst):
        if not inst.url and inst.reported:
            year = inst.reported.year
            if year >= 2012 and year != 2014:
                inst.url = self.urlfmt.format(self.base_url, year)

class DE(Translator):
    base_url = 'https://joblink.delaware.gov'
    default_url = base_url
    fieldsmap = dict(
        company=['Company Name', 'Employer'],
        reported=['Notice Date'],
        location=['City', 'Address', 'ZIP'],
        employees=['Number of Employees Affected'],
        starting=[],
        action=['WARN Type'],
        url=['URL'],
        industry=[],
        report_id=['record_num'],
        naics=[],
        artifacts=[])
    rewrites = dict(
        url=[
            (_r(r'^(/.+)$'), f'{base_url}\\1')
        ],
        report_id=[
            # Compatibility for prior mistake
            (_r(r'^'), '/search/warn_lookups'),
        ]
    )

class FL(Translator):
    base_url = 'https://reactwarn.floridajobs.org'
    default_url = (
        'https://floridajobs.org'
        '/office-directory'
        '/division-of-workforce-services'
        '/workforce-programs'
        '/reemployment-and-emergency-assistance-coordination-team-react'
        '/warn-notices')
    fieldsmap = dict(
        company=['Company Name'],
        reported=['State Notification Date'],
        location=['City'],
        employees=['Employees Affected'],
        starting=['Layoff Date'],
        action=['Notice Type'],
        url=[],
        industry=['Industry'],
        report_id=[],
        naics=[],
        artifacts=['artifacts_json'])
    rewrites = dict(
        company=[
            (_r(r'\n.*'), ''),
            ('Sikorsky, a', 'Sikorsky'),
            (_r(r'Harvest Sherwoord'), 'Harvest Sherwood'),
        ],
    )
    urlfmt = '{}/WarnList/{}?year={}'

    def finish(self, inst: Translation, info: TranslateInfo):
        if inst.company and not inst.location:
            if (text := info.data.get('Company Name')) and '\n' in text:
                it = text.splitlines()[1:]
                it = map(str.strip, it)
                it = filter(None, it)
                addrtext = ', '.join(it)
                addrtext = ' '.join(addrtext.split())
                addrtext = addrtext.replace(',,', ',')
                if addrtext:
                    inst.location = addrtext
        if inst.reported and not inst.url:
            if (year := inst.reported.year) > 2017:
                action = 'viewPreviousYearsPDF' if year <= 2018 else 'Records'
                inst.url = self.urlfmt.format(self.base_url, action, year)

class GA(Translator):
    default_url = 'https://www.tcsg.edu/warn-public-view/'
    fieldsmap = dict(
        company=['Company Name'],
        reported=['submitted_date', 'GA WARN ID', 'First Date of Separation'],
        location=[
            'Company Address',
            'First Location Address',
            'County'],
        employees=[
            'Number of Employees Affected',
            'Total Number of Affected Employees'],
        starting=['First Date of Separation'],
        action=['Type of Layoff or Closure'],
        url=['entry_url'],
        industry=[],
        report_id=['GA WARN ID'],
        naics=['NAICS'],
        artifacts=['artifacts_json'])
    rewrites = dict(
        reported=[
            (_r(r'^(\d{4})(\d{2})\d[A-Z]$'), r'\1-12-31'),
            (_r(r'^(GA|FL|LA)(\d{4})\d{5,}[A-Z]?$'), r'\2-12-31'),
        ],
        location=[
            ('Sm\\', ''),
        ]
    )
    # One observed case of duplicate GA WARN ID for unrelated reports.
    report_id_extra = ['company']

    def finish(self, inst: Translation, info: TranslateInfo):
        """
        Best effort to populated reported date:

        1. Custom scraper collects 'submitted_date'. If this exists, use it. This should
        be valid for new reports.

        2. For historical reports, extract the year from 'GA WARN ID' and use Dec. 31
        of that year. However, if the starting date ('First Date of Separation')
        is earlier, use that.
        
        3. If reported and starting are more than five years apart, discard.
        """
        if not info.data.get('submitted_date'):
            it = (inst.reported, inst.starting)
            inst.reported = min(filter(None, it), default=None)
        if inst.reported and inst.starting:
            if abs(inst.reported.year - inst.starting.year) > 5:
                inst.reported = None

class HI(Translator):
    # TODO: starting
    default_url = 'https://labor.hawaii.gov/wdc/real-time-warn-updates/'
    fieldsmap = dict(
        company=['Company'],
        reported=['Date'],
        location=['location'],
        employees=['jobs'],
        starting=[],
        action=['Notice Type'],
        url=['PDF url'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        reported=[
            (_r(r'#\d+'), ''),
        ],
    )

class IA(Translator):
    default_url = 'https://workforce.iowa.gov/employers/business-resources/warn'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date'],
        location=[],
        employees=['Emp #'],
        starting=['Layoff Date'],
        action=['Notice Type'],
        url=[],
        industry=['Industry'],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'Greyhoung', re.I), 'Greyhound'),
            (_r(r'Industiral', re.I), 'Industrial'),
            (_r(r'Industires', re.I), 'Industries'),
            (_r(r'Mangement', re.I), 'Management'),
            (_r(r'Prinicpal', re.I), 'Principal'),
            (_r(r'Reginoal', re.I), 'Regional'),
            (_r(r'Resporces', re.I), 'Resources'),
            (_r(r'^Transamerican Life', re.I), 'Transamerica Life'),
            ('United Hrdirect', 'United HR Direct'),
            ('Westec Intelligent Surveillanc', 'Westec Intelligent Surveillance'),
        ],
        reported=[
            ('9/1/8/2020', '2020-09-18'),
        ],
        action=[
            ('Mayss Layoff', 'Mass Layoff'),
        ],
        location=[
            (_r(r' (N|S)\.\s*(E|W)\.'), r' \1\2'),
        ],
        industry=[
            (_r(r' adn '), ' and '),
        ],
    )

    def finish(self, inst: Translation, info: TranslateInfo):
        addrkeys = ('Address Line 1', 'City', 'St', 'ZIP')
        addrvals = list(map(info.data.get, addrkeys))
        if all(addrvals):
            location = ', '.join([addrvals[0], ' '.join(addrvals[1:])])
            location = ' '.join(location.split())
            location = strs.rewrite_all(location, self.rewrites['location'])
            if location:
                inst.location = location

class ID(Translator):
    default_url = 'https://www.labor.idaho.gov/warnnotice/'
    fieldsmap = dict(
        company=['Company'],
        reported=['Date of Letter'],
        location=['City'],
        employees=['No. of Employees Affected'],
        starting=['Effective or Commencing Date'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            ("D e n n y ' s", "Denny's"),
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
        ],
    )

class IL(Translator):
    default_url = 'https://dceo.illinois.gov/workforcedevelopment/warn.html'
    fieldsmap = dict(
        company=['Location Name'],
        reported=[
            'Last Report Date',
            'Initial Date Reported'],
        location=['Location City'],
        employees=['Total # of Employees'],
        starting=['Impact Date'],
        action=['Reason'],
        url=[],
        industry=[],
        report_id=['IEBS Id'],
        naics=['NAICS Codes'],
        artifacts=[])
    values_hash_exclude = ['NAICS Codes']
    rewrites = dict(
        company=[
            (_r(r'\*'), ''),
        ],
    )

class IN(Translator):
    base_url = 'https://www.in.gov'
    default_url = f'{base_url}/dwd/warn-notices/current-warn-notices/'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date'],
        location=['City'],
        employees=['Affected Workers'],
        starting=['LO/CL Date'],
        action=['Notice Type'],
        url=['url'],
        industry=[],
        report_id=[],
        naics=['NAICS'],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'\n.*'), ''),
            (_r(r'\s*-\s*Revised.*'), ''),
            (_r(r'Revised \(.*\)$'), ''),
            (_r(r'Additional Documents \(.*\)$'), ''),
            (_r(r'\(Furlough Count by Position\)'), ''),
            (_r(r'\(Doc \d.*\)$'), ''),
            (_r(r'\(additional information and notice\)$'), ''),
            (_r(r'Attachment \d+$'), ''),
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('December 2020', '2020-12-01'),
            ('April/June 2020', '2020-04-01'),
            ('2019', '2019-01-01'),
            ('Q1 2019', '2019-01-01'),
            ('Q1 2018', '2018-01-01'),
            ('Sept. 2016', '2016-09-01'),
            ('End of 2013', '2013-12-31'),
            ('Mid-Year 2014', '2015-06-15'),
            ('year end 2014', '2014-12-31'),
            ('4th Qtr 2012', '2012-10-01'),
            ('Mid February 2012', '2012-02-15'),
            ('3rd Qtr 2012', '2012-10-01'),
            ('07/2010', '2010-07-01'),
            ('Prior to the end of 2009 (as stated in the WARN notice)', '2009-12-01'),
            ('1st Quarter 2009', '2009-01-01'),
            ('3rd Quarter of 2009', '2009-10-01'),
            ('August to December 2008', '2008-08-01'),
            ('01/23/2009-2010', '2009-01-23'),
            ('08/23/2008-2010', '2008-08-23'),
        ],
        action=[
            (_r(r'LO'), 'Layoff'),
            (_r(r'CL'), 'Closure'),
            (_r(r'TR'), 'Transfer'),
            (_r(r'RH'), 'Reduction in Hours'),
            (_r(r'Cond.'), 'Conditional'),
            ('W', 'WARN Notice'),
            ('N/A', ''),
        ],
        naics=[
            (_r(r'^(\d{6})0+$'), r'\1'),
        ]
    )

class KS(Translator):
    default_url = 'https://www.kansasworks.com/search/warn_lookups/new'
    fieldsmap = dict(
        company=['employer'],
        reported=['notice_date'],
        location=['city'],
        employees=['number_of_employees_affected'],
        starting=['LO/CL Date'],
        action=['warn_type'],
        url=['detail_page_url'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'[,\']$'), ''),
            (_r(r'^wal-mart$', re.I), 'Walmart'),
            (_r(r'Thte '), 'The '),
            ("Walgreen's", 'Walgreens'),
        ],
    )

class KY(Translator):
    default_url = 'https://kcc.ky.gov/Pages/News.aspx'
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Date Received'],
        location=['County'],
        employees=['Employees'],
        starting=['Projected Date'],
        action=['Closure or Layoff?'],
        url=['Notice URL'],
        industry=[],
        report_id=[],
        naics=['NAICS Code'],
        artifacts=['artifacts_json'])
    rewrites = dict(
        company=[
            (_r(r'\(EXTENSION OF CONDITIONAL WARN\)'), ''),
        ],
        reported=[
            ('November', ''),
        ],
        starting=[
            ('Mid-January 2009', '2009-01-15'),
            ('November and December 2008', '2008-11-01'),
            ('09/10/208', '2008-10-09'),
            ('45 days, ending 01/28/2013', '2012-12-14'),
            ('Mid August 2012 - 12/2013', '2012-08-15'),
            ('14th - 28th of February 2014', '2014-02-14'),
            ('Decemeber of 2013', '2013-12-01'),
            ('14th - 25th of October 2013', '2013-10-14'),
            ('August or September of 2013', '2013-08-01'),
            ('2041-06-04 00,00,00', '2014-06-04'),
            ('Between June 30, 2014 and July 11, 2014', '2014-06-30'),
            ('September 19, 2014, or within the 14-day period after that date', '2014-09-19'),
            ('September 29, 2014, through October 12, 2014', '2014-09-29'),
            ('Q4, 2014 and are expected to end in Q2, 2015', '2014-10-01'),
            ('21 jobs beginning December 31, 2014,  See WARN', '2014-12-31'),
            ('September 19, 2014/See WARN', '2014-09-19'),
        ],
    )

class LA(Translator):
    base_url = 'https://www.laworks.net'
    default_url = base_url
    values_hash_exclude = ['url', 'Layoff Date', 'Industry']
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Notice Date'],
        location=['Location'],
        employees=['Employees Affected'],
        starting=['Layoff Date'],
        action=[],
        url=['url'],
        industry=['Industry'],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('6/31/09', '2009-06-30'),
            ('5/1820', '2020-05-18'),
            ('10/3124', '2024-10-31'),
        ],
        industry=[
            ('Department Store', 'Department Stores'),
            ('Pre-fabricated Buildings', '332311'),
        ]
    )

class MD(Translator):
    default_url = 'https://www.dllr.state.md.us/employment/warn.shtml'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date'],
        location=['Location'],
        employees=['Total Employees'],
        starting=['Effective Date'],
        action=['Type'],
        url=[],
        industry=[],
        report_id=[],
        naics=['NAICS Code'],
        artifacts=[])
    rewrites = dict(
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('8/2017-12/2018', '2017-08-01'),
            ('12/2017-8/2018', '2017-12-01'),
            ('3/2018-8/2018', '2018-03-01'),
            ('2/29/2014', '2024-02-29'),
            ('4th quarter of this year', ''),
            ('4/82011', '2011-08-04'),
            ('7/62011', '2011-06-07'),
        ],
        reported=[
            ('3/3020/17', '2017-03-30'),
            ('5/62011', '2011-05-06'),
        ],
        employees=[
            *Translator.rewrites['employees'],
            (_r(r'December 2013$'), ''),
        ],
        action=[
            (_r(r'^1(\s.*)?$'), 'Plant Closure'),
            (_r(r'^2(\s.*)?$'), 'Mass Layoff'),
            ('N/A', ''),
        ],
    )

class ME(Translator):
    default_url = 'https://joblink.maine.gov/search/warn_lookups/new'
    fieldsmap = dict(
        company=['employer'],
        reported=['notice_date'],
        location=['address', 'city'],
        employees=['number_of_employees_affected'],
        starting=[],
        action=['warn_type'],
        url=['detail_page_url'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        location=[
            (_r(r';'), ','),
            (_r(r'\s+'), ' '),
        ],
    )

class MI(Translator):
    default_url = 'https://milmi.org/warn/'
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Date Received'],
        location=['City'],
        employees=['Number of Layoffs'],
        starting=[],
        action=['Incident Type'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites=dict(
        company=[
            (_r(r'\u00ef\u00bf\u00bd'), 'e'),
        ],
    )

class MO(Translator):
    default_url = 'https://jobs.mo.gov/warn/'
    fieldsmap = dict(
        company=['Title'],
        reported=['Received', 'Received Sort descending'],
        location=['Location(s)'],
        employees=['# affected'],
        starting=['Layoff date(s)'],
        action=['Type'],
        url=['url'],
        industry=['Industry'],
        report_id=[],
        naics=[],
        artifacts=[])

class MT(Translator):
    default_url = 'https://wsd.dli.mt.gov/wioa/related-links/warn-notice-page'
    fieldsmap = dict(
        company=['Name of Company'],
        reported=['Date of Notice'],
        location=['County'],
        employees=['Number of Employees Affected'],
        starting=['Date of Impact'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class NE(Translator):
    default_url = 'https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN'
    fieldsmap = dict(
        company=['Company'],
        reported=['Date'],
        location=['City', 'Location'],
        employees=['Jobs Affected'],
        starting=[],
        action=['Type'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class NJ(Translator):
    default_url = 'https://www.nj.gov/labor/employer-services/warn/'
    fieldsmap = dict(
        company=['Company'],
        reported=[],
        location=['City'],
        employees=['Workforce Affected'],
        starting=['Effective Date'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    values_hash_exclude = ['scrape_time']
    rewrites = dict(
        company=[
            (_r(r'^Amazon \(.*workers\s*\)$'), 'Amazon'),
        ],
    )

    def finish(self, inst: Translation, info: TranslateInfo):
        month = info.data.get('Month Posted')
        if not month:
            return
        year = int(info.data['worksheet_name'][:4])
        datestr = f'{month} 1, {year}'
        inst.reported = self.parse_date(datestr)
        if inst.reported:
            inst.reported = utils.monthend(inst.reported)
        if inst.starting and (not inst.reported or inst.starting < inst.reported):
            inst.reported = inst.starting

class NM(Translator):
    default_url = 'https://www.dws.state.nm.us/Rapid-Response'
    fieldsmap = dict(
        company=['JOB SITE NAME'],
        reported=['NOTICE DATE', 'RECEIVED DATE'],
        location=['CITY NAME', 'COUNTY NAME'],
        employees=['TOTAL LAYOFF NUMBER'],
        starting=['LAYOFF DATE'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class NY(Translator):
    default_url = 'https://dol.ny.gov/warn-dashboard'
    fieldsmap = dict(
        company=['company_name', 'Company', 'Business Legal Name'],
        reported=[
            'date_posted',
            'Date Posted',
            'Date of WARN Notice',
            'notice_dated',
            'Notice Date',
            'Date of Notice'],
        location=[
            'City',
            'Region',
            'date_posted',
            'Address',
            'Counties',
            'Addresses',
            'Impacted Site Address',
            'Impacted Site County'],
        employees=[
            'Number Affected',
            'Total Number of Affected Workers',
            'Number of Affected Workers'],
        starting=[
            'Closure Start Date',
            'Closing Date',
            'Layoff Date',
            'Layoff Start Date',
            'Date Layoff/Closure Starts'],
        action=['Dislocation Type', 'Reason For Layoff', 'Layoff or Closure?'],
        url=['notice_url'],
        industry=['Industry Type', 'NAICS Description'],
        report_id=['Event Number', 'Event Numbers', 'Event #', 'row_key'],
        naics=[
            'NAISC', # sic
            'NAICS', # in case it's fixed
            'Industry Type'],
        artifacts=['artifacts_json'])
    rewrites = dict(
        naics=[
            ('79', ''),
        ],
        url=[
            (_r(r'^(/.*)$'), r'https://dol.ny.gov\1')
        ],
        report_id=[
            (_r(r' and '), ','),
            (_r(r'[,;]\s*'), ','),
            (_r(r'^.* through .*$'), ''),
        ],
        starting=[
            # (_r(r'.* on or about (.*)\.?$'), r'\1'),
            (_r(r'[\d,]+ employees ', re.I), ''),
            (_r(r'.*within 90 days \(from August 11, 2022/*'), '2022-08-11'),
            (_r(r'^.{20}.*'), ''),
        ]
    )

class OH(Translator):
    default_url = (
        'https://jfs.ohio.gov/wps/portal/gov/jfs/job-services-and-unemployment'
        '/job-services/job-programs-and-services/submit-a-warn-notice'
        '/current-public-notices-of-layoffs-and-closures-sa')
    fieldsmap = dict(
        company=['Company'],
        reported=['Date Received'],
        location=['City/County'],
        employees=['Potential Number Affected'],
        starting=['Layoff Date(s)'],
        action=[],
        url=['URL' ],
        industry=[],
        report_id=['Notice ID'],
        naics=[],
        artifacts=['artifacts_json'])
    rewrites=dict(
        company=[
            (_r(r'&amp;'), '&'),
        ],
        reported=[
            ('01/30/201 7', '2017-01-30'),
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
        ]
    )
    # Amendments use the same Notice ID. The employees count on the
    # amendment is additive, not cumulative, which means we can treat
    # them as separate reports without overcounting in stats.
    report_id_extra = ['reported']

class OK(Translator):
    default_url = 'https://www.employoklahoma.gov/Participants/s/warnnotices'
    fieldsmap = dict(
        company=['Employer', 'employer'],
        reported=['Notice Date', 'notice_date'],
        location=['City', 'city'],
        employees=['number_of_employees_affected'],
        action=['Notice Type', 'warn_type'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'^K[\s-]?mar?t$', re.I), 'Kmart'),
            (_r(r'Hopitality'), 'Hospitality'),
            ('Haliburton Coorperation', 'Halliburton'),
            ('Haliburton', 'Halliburton'),
            ('Siemans Health Services', 'Siemens Health Services'),
            ('Weyerhauser', 'Weyerhaeuser'),
            ('Weyerhouser', 'Weyerhaeuser'),
        ],
    )

class OR(Translator):
    base_url = 'https://ccwd.hecc.oregon.gov/Layoff/WARN'
    default_url = base_url
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Received Date'],
        location=['Location'],
        employees=['Laid Off'],
        starting=['Layoff Date'],
        action=['Layoff Type'],
        url=['WARN#'],
        industry=[],
        report_id=['WARN#'],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'^K[\s-]?mart', re.I), 'Kmart'),
            (_r(r'^Kmart-', re.I), 'Kmart - '),
            (_r(r'[,]$'), ''),
        ],
        url=[
            (_r(r'^(\d+)$'), f'{base_url}/UploadIndex/\\1'),
        ]
    )
    # Duplicate WARN# values for unrelated reports
    report_id_extra = ['reported', 'starting', 'employees', 'location', 'company']

class PA(Translator):
    fieldsmap = dict(
        company=['company'],
        reported=['reported_month'],
        location=['location'],
        employees=['# AFFECTED'],
        starting=['EFFECTIVE DATE', 'EFFECTIVE DATES'],
        action=['CLOSURE OR LAYOFF'],
        url=['url'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    values_hash_exclude = ['location', 'scrape_time', 'raw', 'unparsed', 'url']
    repl_ol = (_r(r'^[1-9][0-9]*\.\s+', re.MULTILINE), '')
    repl_phase = (_r(r'^Phase \d+[:\s]*', re.MULTILINE), '')
    rewrites = dict(
        company=[
            (_r(r'\(UPDATED\)'), ''),
        ],
        location=[
            (_r(r'^\(\*NOTE.*\)'), ''),
            repl_ol,
        ],
        starting=[
            repl_ol,
            repl_phase,
            (_r(r'-', re.MULTILINE), '/'),
        ]
    )

    def finish(self, inst):
        if inst.location:
            inst.location = ', '.join(filter(None, inst.location.splitlines()))

    def value_starting(self, value: str, info: TranslateInfo):
        year = int(info.data['reported_month'].split()[1])
        it = self.parseable_date_strings(value)
        it = (f'{x}/{year}' if x.count('/') == 1 else x for x in it)
        return min(map(self.parse_date, it), default=None)

    def value_reported(self, value):
        month, year = value.split()
        reported = self.parse_date(f'{month} 1, {year}')
        if reported:
            return utils.monthend(reported)

class RI(Translator):
    default_url = 'https://dlt.ri.gov/employers/worker-adjustment-and-retraining-notification-warn'
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Date Received', 'WARN Date'],
        location=['Location of Layoffs'],
        employees=['Number Affected'],
        starting=['Effective Date'],
        action=['Closing Yes/No'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'\s+\(updated .*$', re.I), ''),
            (_r(r'\s*\*\s*$'), ''),
        ],
        action=[
            (_r(r'^yes$', re.I), 'Closing'),
            (_r(r'^no$', re.I), ''),
        ],
        starting=[
            REWRITE_COMPACT_DATERANGE,
        ]
    )

class SC(Translator):
    base_url = 'https://scworks.org'
    default_url = f'{base_url}/employer/employer-programs/risk-closing/layoff-notification-reports'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date', 'Layoff/Closure Date'],
        location=['Location', 'Address', 'County'],
        employees=['Positions', 'Impacted'],
        starting=['Layoff/Closure Date'],
        action=['Closure or Layoff', 'Layoff/Closure'],
        url=['url'],
        industry=[],
        report_id=[],
        naics=['NAICS Code'],
        artifacts=['url'])
    rewrites = dict(
        company=[
            (_r('Servces'), 'Services'),
        ],
        reported=[
            (_r(r'^(\d{4})$'), r'\1-12-31'),
        ],
        starting=[
            REWRITE_DOUBLE_SLASH,
            ('4/8/20/20', '2020-04-08'),
        ],
        url=[
            (_r(r'^(/.*)$'), f'{base_url}\\1')
        ],
    )
    values_hash_exclude = ['url']

    def value_artifacts(self, value):
        year = int(value.split('/')[-1][:4])
        return {f'{year}.pdf': value}

    def finish(self, inst: Translation, info: TranslateInfo):
        """
        Best effort to populated reported date:

        1. New reports have 'Notice Date'

        2. For historical reports, use Dec. 31 of the year. However, if the
        starting date is earlier, use that.
        """
        if not info.data.get('Notice Date'):
            it = (inst.reported, inst.starting)
            inst.reported = min(filter(None, it), default=None)

class SD(Translator):
    default_url = 'https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx'
    fieldsmap = dict(
        company=['Company'],
        reported=['Date Received'],
        location=['Location'],
        employees=['Employees Affected'],
        starting=[],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class TN(Translator):
    default_url = 'https://www.tn.gov/workforce/general-resources/major-publications0/major-publications-redirect/reports.html'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Date', 'Received Date', 'Notice Date'],
        location=['City', 'County'],
        employees=['No. Of Employees'],
        starting=['Effective Date'],
        action=['Layoff/Closure'],
        url=[],
        industry=[],
        report_id=['Notice ID'],
        naics=[],
        artifacts=[])
    rewrites = dict(
        reported=[
            ('2018/4/ 27', '2018/4/27'),
        ],
        report_id=[
            (_r(r'^#'), ''),
        ],
        company=[
            (',', ''),
            ('.', ''),
        ],
        starting=[
            ('October 2021', '2021-10-01'),
            ('Late September 2019', '2019-09-20'),
            (_r(r'February 2020'), '2020-02-01'),
            (_r(r'Apri '), 'April'),
        ]
    )
    report_id_extra = ['reported', 'starting', 'employees', 'location']

class TX(Translator):
    default_url = 'https://www.twc.texas.gov/data-reports/warn-notice'
    fieldsmap = dict(
        company=['JOB_SITE_NAME'],
        reported=['NOTICE_DATE'],
        location=['CITY_NAME'],
        employees=['TOTAL_LAYOFF_NUMBER'],
        starting=['Layoff Type', 'LayOff_Date'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=['artifact_url'])
    rewrites = dict(
        company=[
            (_r(r'_x000D_'), ''),
            (_r(r"'$"), ''),
            # TODO: Dallas4 Plano2 etc.
            (_r(r'(dallas|plano|austin|antonio|houston|worth|el paso)\d', re.I), r'\1'),
            (_r(r'^Sprint-.*'), 'Sprint'),
        ],
        location=[
            (_r(r'^ft\.? worth$', re.I), 'Fort Worth'),
        ],
        starting=[
            ('1930-03-30 00:00:00', '2020-03-30'),
            ('1930-03-31 00:00:00', '2020-03-31'),
        ],
    )

    def finish(self, inst):
        if inst.reported and inst.starting:
            if inst.starting.year == 2027 and inst.reported.year == 2017:
                inst.starting = inst.starting.replace(year=inst.reported.year)

class UT(Translator):
    default_url = 'https://jobs.utah.gov/employer/business/warnnotices.html'
    fieldsmap = dict(
        company=['Company Name'],
        reported=['Date of Notice'],
        location=['Location'],
        employees=['Affected Workers'],
        starting=['Date of Notice'],
        action=[],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    values_hash_exclude = ['scrape_time']
    rewrites = dict(
        company=[
            (_r(r'â'), ''),
            (_r(r'navbar-headers'), ''),
            (_r(r'\s*\(Amended\)$'), ''),
            (_r(r'PremiumWindows'), 'Premium Windows'),
        ],
        reported=[
            REWRITE_DOUBLE_SLASH,
            ('09/31/10', '2010-09-30'),
            ('05/2009', '2009-05-01'),
        ],
    )

class VA(Translator):
    default_url = 'https://www.virginiaworks.gov/warn-notices/'
    # action_headers = ['Closure', 'Layoff', 'Permanent Reduction', 'Realignment']
    fieldsmap = dict(
        company=['Company', 'Company Name'],
        reported=['Notice Date'],
        location=['Location', 'Location City'],
        employees=['Employees Affected'],
        starting=['Impact Date'],
        action=['Reduction in Force'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        starting=[
            ('10/01/1973', '2020-10-01'),
        ],
        action=[
            (_r(r'<br>'), ' '),
            (_r(r' $'), ''),
        ]
    )

class VT(Translator):
    default_url = 'https://www.vermontjoblink.com/search/warn_lookups/new'
    fieldsmap = dict(
        company=['employer'],
        reported=['notice_date'],
        location=['city'],
        employees=['number_of_employees_affected'],
        starting=['Impact Date'],
        action=['warn_type'],
        url=['detail_page_url'],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class WA(Translator):
    default_url = 'https://esd.wa.gov/about-employees/WARN'
    fieldsmap = dict(
        company=['Company'],
        reported=['Received Date'],
        location=['Location'],
        employees=['# of Workers'],
        starting=['Layoff Start Date'],
        action=['Closure Layoff', 'Type of Layoff'],
        url=[],
        industry=[],
        report_id=[],
        naics=[],
        artifacts=[])

class WI(Translator):
    default_url = 'https://dwd.wisconsin.gov/dislocatedworker/warn/'
    fieldsmap = dict(
        company=['Company'],
        reported=['Notice Received'],
        location=['City'],
        employees=['Affected Workers'],
        starting=['Layoff Begin Date'],
        action=['Original Notice Type / Update Type'],
        url=[],
        industry=['NAICS Description'],
        report_id=[],
        naics=[],
        artifacts=[])
    rewrites = dict(
        company=[
            (_r(r'\s*\(CORRECTED\)$'), ''),
        ],
        action=[
            ('WR', 'Workforce Reduction'),
            ('CL', 'Facility Closure'),
        ],
        industry=[
            (_r(r' & '), ' and '),
            (_r(r'Mfg\.?'), 'Manufacturing'),
        ]
    )
