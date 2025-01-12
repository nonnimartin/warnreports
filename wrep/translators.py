from __future__ import annotations

import inspect
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html import unescape as html_unescape
from pathlib import Path
from typing import Any, ClassVar, Iterable

from pydantic import HttpUrl

from . import orm, settings, utils
from .models import ValidationError
from .orm import ReportMod
from .ref.tz import zoneinfos

_r = re.compile

NAMESPACE = uuid.uuid5(settings.NAMESPACE, 'Report')
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
translators: dict[str, type[Translator]] = {}
type Entry = dict[str, Any]
type Row = dict[str, str]

class Translator:

    tz: ClassVar = timezone.utc
    headermap: ClassVar[dict[str, str|list[str]]] = {}
    default_url: ClassVar[str|None] = None
    values_hash_exclude: ClassVar[list[str]] = []
    report_id_extra: ClassVar[list[str]] = []
    rewrites: ClassVar[dict[str, list[tuple[str|re.Pattern, str]]]] = dict(
        employees=[
            (_r(r'(\d),(\d)'), r'\1\2'), # remove comma separators
            (_r(r'\d{1,2}/\d{1,2}/\d{2,4}'), ''), # remove dates M/D/Y
            (_r(r'\d{1,2}/\d{2,4}'), ''), # remove dates M/Y
            (_r(r'\d{4}-\d{2}-\d{2}'), ''), # remove dates YYYY-MM-DD
        ]
    )
    _session: orm.Session|None = None

    @property
    @contextmanager
    def session(self):
        if self._session:
            yield self._session
        else:
            with orm.SessionLocal() as session:
                yield session

    @session.setter
    def session(self, value: orm.Session|None) -> None:
        self._session = value

    def entry(self, row: Row) -> Entry:
        'Translate a source row to an entry'
        entry = {}
        for header, fields in self.headermap.items():
            if header not in row:
                continue
            if isinstance(fields, str):
                fields = [fields]
            for field in fields:
                if field in entry:
                    continue
                value = self.value(field, row[header], row)
                if value is not None and value != '':
                    entry[field] = value
        self.finish(entry, row)
        return entry

    def value(self, field: str, value: str, row: Row) -> Any:
        'Translate a field value'
        value = self.sanitize(value)
        value = self.rewrite(field, value)
        method = f'value_{field}'
        if (func := getattr(self, method, None)):
            args = (value,)
            if len(inspect.signature(func).parameters) > 1:
                args += (row,)
            value = func(*args)
        return value

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

    def value_url(self, value: str) -> str|None:
        try:
            HttpUrl(value)
        except ValidationError:
            value = None
        return value

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

    def value_artifacts(self, value: str) -> dict[str, str]:
        try:
            data = dict(json.loads(value))
        except json.JSONDecodeError:
            if value.endswith('.pdf') or value.endswith('.xlsx'):
                data = {Path(value).name: value}
            else:
                data = {}
        artifacts = {}
        for path, url in data.items():
            try:
                HttpUrl(url)
                Path(path)
            except (ValidationError, ValueError):
                continue
            artifacts[path] = url
        return artifacts

    def value_scrape_time(self, value: str) -> datetime|None:
        return utils.parse_date(value)

    def sanitize(self, value: str) -> str:
        return value.translate(ASCII_TRANS).strip()

    def rewrite(self, field: str, value: str) -> str:
        if field in self.rewrites:
            for srch, repl in self.rewrites[field]:
                if srch == value:
                    value = repl
                elif isinstance(srch, re.Pattern):
                    value = srch.sub(repl, value)
        return value

    def finish(self, entry: Entry, row: Row) -> None:
        if not entry.get('url') and self.default_url:
            entry['url'] = self.default_url
        values_id = self.values_hash_uuid(row)
        self._extend_report_id(entry)
        report_id = entry.get('report_id')
        if report_id:
            report_id = uuid.uuid5(self.namespace, report_id)
        else:
            report_id = values_id
        entry.update(id=report_id, values_id=values_id, state=self.state, row=row)
        self._fill_mod(entry)

    def _extend_report_id(self, entry: Entry) -> None:
        if (report_id := entry.get('report_id')):
            parts = [report_id]
            for value in map(entry.get, self.report_id_extra):
                if isinstance(value, datetime):
                    parts.append(value.strftime(f'%Y-%m-%d'))
                elif isinstance(value, int):
                    parts.append(str(value))
                elif isinstance(value, str):
                    parts.append(PAT_NONALPHANUM.sub('', value).upper())
            entry['report_id'] = '_'.join(parts)

    def _fill_mod(self, entry: Entry) -> None:
        scrape_time: datetime|None = entry.pop('scrape_time', None)
        if scrape_time:
            stmt = orm.select(ReportMod).where(ReportMod.id == entry['id'])
            with self.session as session:
                repmod = session.scalar(stmt)
                if not repmod:
                    repmod = ReportMod(id=entry['id'], ns=self.namespace)
                if not repmod.first_scraped or scrape_time < repmod.first_scraped:
                    repmod.first_scraped = scrape_time
                    session.add(repmod)
                    session.commit()
                scraped = repmod.first_scraped
            reported = entry.get('reported')
            if reported and scraped < reported:
                reported = scraped.replace(tzinfo=self.tz)
                offset = reported.utcoffset()
                if offset:
                    reported += offset
                reported = reported.replace(
                    hour=0,
                    minute=0,
                    second=0,
                    microsecond=0)
                entry['reported'] = reported

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
        value = PAT_DATESTRCLEAN.sub(' ', value).strip(' /-')
        yield from filter(self.parse_date, value.split())

    def values_hash_uuid(self, row: Row) -> uuid.UUID:
        if self.values_hash_exclude:
            row = dict(row)
            for header in self.values_hash_exclude:
                row.pop(header, None)
        return uuid.uuid5(self.namespace, json.dumps(list(row.values())))

    def __init_subclass__(cls) -> None:
        cls.rewrites = Translator.rewrites | cls.rewrites
        if len(state := cls.__name__.upper()) == 2:
            cls.state = state
            cls.tz = zoneinfos[state]
            cls.namespace = uuid.uuid5(NAMESPACE, state)
            translators[state] = cls

# 1/1/2000-1/2/2000 -> 1/1/2000 - 1/2/2000
REWRITE_COMPACT_DATERANGE = (_r(r'(/\d+)-(\d+/)'), r'\1 - \2')

# // -> /
REWRITE_DOUBLE_SLASH = (_r('//'), '/')

REWRITE_UNESCAPE_HTML = (_r(r'.*'), lambda m: html_unescape(m[0]))

class ReportedYearToUrl(Translator):

    def is_valid_url_year(self, year: int) -> bool:
        return True

    def get_reported_year_url(self, year: int) -> str|None:
        pass

    def finish(self, entry: Entry, row: Row) -> None:
        if not entry.get('url'):
            reported = entry.get('reported')
            if isinstance(reported, datetime) and self.is_valid_url_year(reported.year):
                url = self.get_reported_year_url(reported.year)
                if url:
                    entry['url'] = url
        super().finish(entry, row)

class AK(Translator):
    default_url = 'https://jobs.alaska.gov/RR/WARN_notices.htm'
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        'Notes': 'action',
        'url': ['url', 'report_id'],
    }
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
    headermap = {
        'Company': 'company',
        'Initial Report Date': 'reported',
        'City': 'location',
        'Planned # Affected Employees': 'employees',
        'Closing or Layoff': 'action',
        'Planned Starting Date': 'starting',
        'record_number': 'report_id',
    }
    rewrites = dict(
        action=[
            (_r(r'\s*\*$'), ''),
        ]
    )

class AZ(Translator):
    default_url = 'https://www.azjobconnection.gov/search/warn_lookups/new'
    headermap = {
        'employer': 'company',
        'notice_date': ['reported', 'starting'],
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': ['url', 'report_id'],
    }
    rewrites = dict(
        report_id=[
            (_r(r'^https://.+/(\d+)$'), r'\1'),
        ]
    )

class CA(Translator):
    default_url = 'https://edd.ca.gov/en/Jobs_and_Training/Layoff_Services_WARN'
    rewrite_url = (
        _r(r'^(.+)$'),
        r'https://edd.ca.gov/siteassets/files/jobs_and_training/warn/\1')
    headermap = {
        'company': 'company',
        'notice_date': 'reported',
        'address': 'location',
        'num_employees': 'employees',
        'layoff_or_closure': 'action',
        'effective_date': 'starting',
        'source_file': ['url', 'artifacts'],
    }
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
        url=[
            rewrite_url,
        ],
        artifacts=[
            rewrite_url,
        ],
    )

class CO(Translator):
    default_url = 'https://cdle.colorado.gov/employers/layoff-separations/layoff-warn-list'
    headermap = {
        'company': 'company',
        'received_date': 'reported',
        'notice_date': 'reported',
        'city': 'location',
        'jobs': 'employees',
        'reason': 'action',
        'begin_date': 'starting',
        'naics': 'naics',
    }
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
        ]
    )

class CT(ReportedYearToUrl):
    base_url = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'
    default_url = f'{base_url}/warnreports.htm'
    headermap = {
        'affected_company': 'company',
        'warn_date': 'reported',
        'layoff_location': 'location',
        'number_workers': 'employees',
        'closing': 'action',
        'layoff_date': 'starting'
    }
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

    def get_reported_year_url(self, year: int) -> str | None:
        return f'{self.base_url}/warn{year}.htm'

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2015

class DC(ReportedYearToUrl):
    base_url = 'https://does.dc.gov'
    default_url = f'{base_url}/page/rapid-response'
    headermap = {
        'Organization Name': 'company',
        'Notice Date': 'reported',
        'Number toEmployees Affected': 'employees',
        'Code Type': 'action',
        'Effective Layoff Date': 'starting'
    }
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

    def get_reported_year_url(self, year: int) -> str:
        return f'{self.base_url}/page/industry-closings-and-layoffs-warn-notifications-{year}'

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2012 and year != 2014

class DE(Translator):
    base_url = 'https://joblink.delaware.gov'
    default_url = base_url
    headermap = {
        'Company Name': 'company',
        'Employer': 'company',
        'Notice Date': 'reported',
        'City': 'location',
        'Address': 'location',
        'ZIP': 'location',
        'Number of Employees Affected': 'employees',
        'WARN Type': 'action',
        'URL': ['url', 'report_id'],
    }
    rewrites = dict(
        url=[
            (_r(r'^(/.+)$'), f'{base_url}\\1')
        ],
        report_id=[
            (_r(r'/(\d+)$'), r'\1')
        ]
    )

class FL(ReportedYearToUrl):
    base_url = 'https://reactwarn.floridajobs.org'
    default_url = 'https://floridajobs.org/office-directory/division-of-workforce-services/workforce-programs/reemployment-and-emergency-assistance-coordination-team-react/warn-notices'
    headermap = {
        'Company Name': 'company',
        'State Notification Date': 'reported',
        'City': 'location',
        'Employees Affected': 'employees',
        'Notice Type': 'action',
        'Layoff Date': 'starting',
        'download': 'url',
        'Industry': 'industry',
    }
    rewrites = dict(
        company=[
            (_r(r'\n.*'), ''),
            ('Sikorsky, a', 'Sikorsky'),
        ],
        url=[
            (_r(r'^(.+)$'), f'{base_url}/WarnList/DownloadAzureFile?file=\\1'),
        ]
    )

    def get_reported_year_url(self, year: int) -> str:
        action = 'viewPreviousYearsPDF' if year <= 2018 else 'Records'
        return f'{self.base_url}/WarnList/{action}?year={year}'

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2017

class GA(Translator):
    default_url = 'https://www.tcsg.edu/warn-public-view/'
    headermap = {
        'Company Name': 'company',
        'submitted_date': 'reported',
        'GA WARN ID': ['report_id', 'reported'],
        'Type of Layoff or Closure': 'action',
        'First Date of Separation': ['starting', 'reported'],
        'Number of Employees Affected': 'employees',
        'Total Number of Affected Employees': 'employees',
        'First Location Address': 'location',
        'County': 'location',
        'NAICS': 'naics',
        'entry_url': 'url',
    }
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

    def finish(self, entry: Entry, row: Row) -> None:
        """
        Best effort to populated reported date:

        1. Custom scraper collects 'submitted_date'. If this exists, use it. This should
        be valid for new reports.

        2. For historical reports, extract the year from 'GA WARN ID' and use Dec. 31
        of that year. However, if the starting date ('First Date of Separation')
        is earlier, use that.
        
        3. If reported and starting are more than five years apart, discard.
        """
        if not row.get('submitted_date'):
            it = map(entry.get, ['reported', 'starting'])
            entry['reported'] = min(filter(None, it), default=None)
        reported: datetime|None = entry.get('reported')
        starting: datetime|None = entry.get('starting')
        if reported and starting:
            if abs(reported.year - starting.year) > 5:
                reported = None
                entry['reported'] = reported
        super().finish(entry, row)

class HI(Translator):
    # TODO: starting
    default_url = 'https://labor.hawaii.gov/wdc/real-time-warn-updates/'
    headermap = {
        'Company': 'company',
        'Date': 'reported',
        'location': 'location',
        'jobs': 'employees',
        'Notice Type': 'action',
        'PDF url': 'url',
    }
    rewrites = dict(
        reported=[
            (_r(r'#\d+'), ''),
        ],
    )

class IA(Translator):
    default_url = 'https://workforce.iowa.gov/employers/business-resources/warn'
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'City': 'location',
        'Emp #': 'employees',
        'Notice Type': 'action',
        'Layoff Date': 'starting'
    }
    rewrites = dict(
        company=[
            (_r(r'Prinicpal'), 'Principal'),
        ],
        reported=[
            ('9/1/8/2020', '2020-09-18'),
        ],
        action=[
            ('Mayss Layoff', 'Mass Layoff'),
        ],
    )

class ID(Translator):
    default_url = 'https://www.labor.idaho.gov/warnnotice/'
    headermap = {
        'Company': 'company',
        'Date of Letter': 'reported',
        'City': 'location',
        'No. of Employees Affected': 'employees',
        'Effective or Commencing Date': 'starting'
    }
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
    headermap = {
        'Location Name': 'company',
        'Location City': 'location',
        'Total # of Employees': 'employees',
        'Last Report Date': 'reported',
        'Initial Date Reported': 'reported',
        'Impact Date': 'starting',
        'Reason': 'action',
        'NAICS Codes': 'naics',
        'IEBS Id': 'report_id',
        'artifacts_json': 'artifacts',
    }
    rewrites = dict(
        company=[
            (_r(r'\*'), ''),
        ],
    )

class IN(Translator):
    base_url = 'https://www.in.gov'
    default_url = f'{base_url}/dwd/warn-notices/current-warn-notices/'
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Notice Type': 'action',
        'LO/CL Date': 'starting',
        'NAICS': 'naics',
        'url': 'url',
    }
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
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'LO/CL Date': 'starting',
        'detail_page_url': 'url',
    }
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
    headermap = {
        'Date Received': 'reported',
        'Company Name': 'company',
        'County': 'location',
        'Employees': 'employees',
        'Closure or Layoff?': 'action',
        'Projected Date': 'starting',
        'Notice URL': 'url',
        'NAICS Code': 'naics'
    }
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
    headermap = {
        'Company Name': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        'Industry': 'industry',
        'url': 'url',
    }
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
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Total Employees': 'employees',
        'Type': 'action',
        'Effective Date': 'starting',
        'NAICS Code': 'naics',
    }
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
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class MI(Translator):
    default_url = 'https://milmi.org/warn/'

    headermap = {
        'Company Name': 'company',
        'City': 'location',
        'Date Received': 'reported',
        'Incident Type': 'action',
        'Number of Layoffs': 'employees'
    }

class MO(Translator):
    default_url = 'https://jobs.mo.gov/warn/'
    headermap = {
        'Title': 'company',
        'Received': 'reported',
        'Received Sort descending': 'reported',
        'Location(s)': 'location',
        '# affected': 'employees',
        'Type': 'action',
        'Layoff date(s)': 'starting',
        'Industry': 'industry',
        'url': 'url',
    }

class MT(Translator):
    default_url = 'https://wsd.dli.mt.gov/wioa/related-links/warn-notice-page'
    headermap = {
        'Date of Notice' : 'reported',
        'Name of Company': 'company',
        'County': 'location',
        'Date of Impact': 'starting',
        'Number of Employees Affected': 'employees',
    }

class NE(Translator):
    default_url = 'https://dol.nebraska.gov/ReemploymentServices/LayoffServices/LayoffsAndDownsizingWARN'
    headermap = {
        'Date': 'reported',
        'Company': 'company',
        'Type': 'action',
        'Jobs Affected': 'employees',
        'City' : 'location',
        'Location' : 'location',
    }

class NJ(Translator):
    default_url = 'https://www.nj.gov/labor/employer-services/warn/'
    headermap = {
        'Company': 'company',
        'City': 'location',
        'Effective Date': 'starting',
        'Workforce Affected': 'employees',
        'scrape_time': 'scrape_time',
    }
    values_hash_exclude = ['scrape_time']

    def finish(self, entry: Entry, row: Row) -> None:
        month: str|None = row.get('Month Posted')
        if month:
            year = int(row['worksheet_name'][:4])
            datestr = f'{month} 1, {year}'
            reported = self.parse_date(datestr)
            if reported:
                for days in reversed(range(28, 31)):
                    dt = reported + timedelta(days=days)
                    if dt.month == reported.month:
                        reported = dt
                        break
            starting: datetime|None = entry.get('starting')
            if starting and starting < reported:
                reported = starting
            entry['reported'] = reported
        super().finish(entry, row)

class NM(Translator):
    default_url = 'https://www.dws.state.nm.us/Portals/0/DM/Business/2024_WARN.pdf'
    headermap = {
        'NOTICE DATE' : 'reported',
        'JOB SITE NAME' : 'company',
        'COUNTY NAME' : 'location',
        'TOTAL LAYOFF NUMBER' : 'employees',
        'LAYOFF DATE': 'starting',
        'LAYOFF DATE': 'reported',
        'CITY NAME': 'location',
    }

class NY(Translator):
    default_url = 'https://dol.ny.gov/warn-notices'
    headermap = {
        'company_name': 'company',
        'Company': 'company',
        'notice_dated': 'reported',
        'Notice Date' : 'reported',
        'Date of Notice': 'reported',
        'Number Affected': 'employees',
        'Total Number of Affected Workers': 'employees',
        'Closure Start Date': 'starting',
        'Closing Date': 'starting',
        'Layoff Date': 'starting',
        'Layoff Start Date': 'starting',
        'City': 'location',
        'Region': 'location',
        'date_posted': 'location',
        'Address': 'location',
        'Counties': 'location',
        'Addresses': 'location',
        'Dislocation Type': 'action',
        'Reason For Layoff': 'action',
        'notice_url': 'url',
        'NAISC': 'naics', # sic
        'NAICS': 'naics', # in case it's fixed
        'Industry Type': ['naics', 'industry'],
        'NAICS Description': 'industry',
        'Event Number': 'report_id',
        'Event Numbers': 'report_id',
        'Event #': 'report_id',
        'artifacts_json': 'artifacts',
    }
    rewrites = dict(
        naics=[
            ('79', ''),
        ],
        url=[
            (_r(r'^(/.*)$'), r'https://dol.ny.gov\1')
        ],
        report_id=[
            (_r(r' and '), ','),
            (_r(r'^.*[^\d,-].*$'), ''),
        ],
        starting=[
            # (_r(r'.* on or about (.*)\.?$'), r'\1'),
            (_r(r'[\d,]+ employees ', re.I), ''),
            (_r(r'.*within 90 days \(from August 11, 2022/*'), '2022-08-11'),
            (_r(r'^.{20}.*'), ''),
        ]
    )

class OH(Translator):
    default_url = 'https://jfs.ohio.gov/wps/portal/gov/jfs/job-services-and-unemployment/job-services/job-programs-and-services/submit-a-warn-notice/current-public-notices-of-layoffs-and-closures-sa'
    headermap = {
        'Company' : 'company',
        'Potential Number Affected' : 'employees',
        'Date Received' : 'reported',
        'URL' : 'url',
        'City/County' : 'location',
        'Layoff Date(s)': 'starting',
        'Notice ID' : 'report_id',
        'artifacts_json': 'artifacts',
    }
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
    default_url = 'https://okjobmatch.com/search/warn_lookups/new'
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city' : 'location',
        'number_of_employees_affected': 'employees',
        'warn_type' : 'action',
        'detail_page_url' : 'url'
    }
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
    headermap = {
        'Company Name': 'company',
        'Received Date': 'reported',
        'Location': 'location',
        'Laid Off': 'employees',
        'Layoff Type': 'action',
        'Layoff Date': 'starting',
        'WARN#': ['url', 'report_id'],
    }
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
    headermap = {
        'company': 'company',
        'location': 'location',
        'scrape_time': 'scrape_time',
        'EFFECTIVE DATE': 'starting',
        'EFFECTIVE DATES': 'starting',
        '# AFFECTED': 'employees',
        'CLOSURE OR LAYOFF': 'action',
        'reported_month': 'reported',
        'url': 'url',
    }
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
        ]
    )

    def value_location(self, value):
        return ', '.join(filter(None, super().value_location(value).splitlines()))

    def value_starting(self, value: str, row: Row):
        year = int(row['reported_month'].split()[1])
        it = self.parseable_date_strings(value)
        it = (self._fill_date_string(x, year) for x in it)
        return super().value_starting(' '.join(it))

    def _fill_date_string(self, value: str, year: int) -> str:
        value = value.replace('-', '/')
        if value.count('/') == 1:
            value += f'/{year}'
        return value

    def value_reported(self, value):
        month, year = value.split()
        reported = self.parse_date(f'{month} 1, {year}')
        if reported:
            for days in reversed(range(28, 31)):
                dt = reported + timedelta(days=days)
                if dt.month == reported.month:
                    reported = dt
                    break
            return reported

class RI(Translator):
    default_url = 'https://dlt.ri.gov/employers/worker-adjustment-and-retraining-notification-warn'
    headermap = {
        'Date Received': 'reported',
        'WARN Date': 'reported',
        'Company Name': 'company',
        'Location of Layoffs': 'location',
        'Number Affected': 'employees',
        'Effective Date': 'starting',
        'Closing Yes/No': 'action',
    }
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
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Layoff/Closure Date': 'reported',
        'Layoff/Closure Date': 'starting',
        'Location': 'location',
        'Address': 'location',
        'County': 'location',
        'Positions': 'employees',
        'Impacted': 'employees',
        'Closure or Layoff': 'action',
        'Layoff/Closure': 'action',
        'NAICS Code': 'naics',
        'url': ['url', 'artifacts'],
    }
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

    def finish(self, entry: Entry, row: Row) -> None:
        """
        Best effort to populated reported date:

        1. New reports have 'Notice Date'

        2. For historical reports, use Dec. 31 of the year. However, if the
        starting date is earlier, use that.
        """
        if not row.get('Notice Date'):
            it = map(entry.get, ['reported', 'starting'])
            entry['reported'] = min(filter(None, it), default=None)
        super().finish(entry, row)

class SD(Translator):
    default_url = 'https://dlr.sd.gov/workforce_services/businesses/warn_notices.aspx'
    headermap = {
        'Company' : 'company',
        'Location' : 'location',
        'Date Received' : 'reported',
        'Employees Affected' : 'employees',

    }

class TN(Translator):
    default_url = 'https://www.tn.gov/workforce/general-resources/major-publications0/major-publications-redirect/reports.html'
    headermap = {
        'Notice Date': 'reported',
        'Company' : 'company',
        'City' : 'location',
        'Effective Date' : 'starting',
        'Received Date' : 'reported',
        'Notice Date' : 'reported',
        'County' : 'location',
        'No. Of Employees': 'employees',
        'Layoff/Closure': 'action',
        'Notice ID': 'report_id',
    }
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
        ]
    )
    report_id_extra = ['reported', 'starting', 'employees', 'location']

class TX(Translator):
    default_url = 'https://www.twc.texas.gov/data-reports/warn-notice'
    headermap = {
        'JOB_SITE_NAME': 'company',
        'NOTICE_DATE': 'reported',
        'CITY_NAME': 'location',
        'TOTAL_LAYOFF_NUMBER': 'employees',
        'Layoff Type': 'action',
        'LayOff_Date': 'starting',
        'artifact_url': 'artifacts',
    }
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

    def finish(self, entry: Entry, row: Row) -> None:
        reported: datetime|None = entry.get('reported')
        starting: datetime|None = entry.get('starting')
        if reported and starting:
            if starting.year == 2027 and reported.year == 2017:
                starting = starting.replace(year=reported.year)
                entry['starting'] = starting
        super().finish(entry, row)

class UT(Translator):
    default_url = 'https://jobs.utah.gov/employer/business/warnnotices.html'
    headermap = {
        'Company Name': 'company',
        'Date of Notice': ['reported', 'starting'],
        'Location': 'location',
        'Affected Workers': 'employees',
        'scrape_time': 'scrape_time',
    }
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
    default_url = 'https://www.vec.virginia.gov/warn-notices'
    # action_headers = ['Closure', 'Layoff', 'Permanent Reduction', 'Realignment']
    headermap = {
        'Company': 'company',
        'Company Name': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Location City': 'location',
        'Employees Affected': 'employees',
        'Impact Date': 'starting',
        'Reduction in Force': 'action',
    }
    rewrites = dict(
        starting=[
            ('10/01/1973', '2020-10-01'),
        ],
        action=[
            (_r(r'<br>'), ' '),
            (_r(r' $'), ''),
        ]
    )

    # def finish(self, entry: Entry, row: Row) -> None:
    #     entry['action'] = '/'.join(
    #         v for v in self.action_headers
    #         if row.get(v) == 'Yes')
    #     super().finish(entry, row)

class VT(Translator):
    default_url = 'https://www.vermontjoblink.com/search/warn_lookups/new'
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'Impact Date': 'starting',
        'detail_page_url': 'url'
    }

class WA(Translator):
    default_url = 'https://esd.wa.gov/about-employees/WARN'
    headermap = {
        'Company' : 'company',
        '# of Workers' : 'employees',
        'Layoff Start Date' : 'starting',
        'Closure Layoff' : 'action',
        'Type of Layoff' : 'action',
        'Location' : 'location',
        'Received Date' : 'reported'
    }

class WI(Translator):
    default_url = 'https://dwd.wisconsin.gov/dislocatedworker/warn/'
    headermap = {
        'Company': 'company',
        'Notice Received': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Original Notice Type / Update Type': 'action',
        'Layoff Begin Date': 'starting',
        'NAICS Description': 'industry',
    }
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
