from __future__ import annotations

import re
from datetime import datetime
from html import unescape as html_unescape
from typing import Any

from . import utils
from .models import HttpUrl, ValidationError

PAT_SPACES = re.compile(r'\s+')
PAT_NONDIGITS = re.compile(r'[^\d]+')
ASCII_TRANS = {
    0x0009: ' ',
    0x0080: ' ',
    0x0093: '',
    0x0095: ' ',
    0x2013: '-',
    0x2019: "'",
}
logger = utils.get_logger('translators')
translators: dict[str, type[Translator]] = {}

_r = re.compile

class Translator:

    headermap: dict[str, str] = {}
    default_url: str|None = None
    rewrites: dict[str, list[tuple[str|re.Pattern, str]]] = dict(
        employees=[
            (_r(r'(\d),(\d)'), r'\1\2'), # remove comma separators
            (_r(r'\d{1,2}/\d{1,2}/\d{2,4}'), ''), # remove dates M/D/Y
            (_r(r'\d{1,2}/\d{2,4}'), ''), # remove dates M/Y
            (_r(r'\d{4}-\d{2}-\d{2}'), ''), # remove dates YYYY-MM-DD
        ]
    )

    def entry(self, row: dict[str, Any]) -> dict[str, Any]:
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
                value = self.value(field, row[header])
                if value is not None and value != '':
                    entry[field] = value
        self.finish(entry, row)
        return entry

    def value(self, field: str, value: str) -> Any:
        'Translate a field value'
        value = self.sanitize(value)
        value = self.rewrite(field, value)
        method = f'value_{field}'
        if hasattr(self, method):
            value = getattr(self, method)(value)
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
        value = PAT_SPACES.sub(' ', value)
        value = value.strip()
        return value

    def value_action(self, value: str) -> str:
        return value

    def value_url(self, value: str) -> str|None:
        try:
            HttpUrl(value)
        except ValidationError:
            value = None
        return value

    def value_naics(self, value: str) -> list[int]:
        values = set()
        for value in re.split(r'[\s,]+', value):
            if value in ('31-33', '44-45', '48-49'):
                minmax = list(map(int, value.split('-')))
                values.update(range(minmax[0], minmax[1] + 1))
                continue
            value = utils.parse_int(value)
            if value and 2 <= len(str(value)) <= 6:
                values.add(value)
        return sorted(values)

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

    def finish(self, entry: dict[str, Any], row: dict[str, str]) -> None:
        if not entry.get('url') and self.default_url:
            entry['url'] = self.default_url

    def parse_date(self, value: str) -> datetime|None:
        dt = utils.parse_date(value)
        if dt and (
            # If we parsed a time, something likely went wrong.
            not any((dt.hour, dt.minute, dt.second)) and
            # Sane date range
            1980 <= dt.year <= utils.now().year + 10):
            return dt

    def parse_dates(self, value: str) -> list[datetime]:
        dt = self.parse_date(value)
        if dt:
            return [dt]
        value = re.sub(r'[^\d\s/-]', ' ', value).strip(' /-')
        it = map(self.parse_date, PAT_SPACES.split(value))
        return list(filter(None, it))

    def __init_subclass__(cls, state: str|None = None) -> None:
        cls.rewrites = Translator.rewrites | cls.rewrites
        if state:
            translators[state.upper()] = cls

# 1/1/2000-1/2/2000 -> 1/1/2000 - 1/2/2000
REWRITE_COMPACT_DATERANGE = (_r(r'(/\d+)-(\d+/)'), r'\1 - \2')

# // -> /
REWRITE_DOUBLE_SLASH = (_r('//'), '/')

REWRITE_UNESCAPE_HTML = (_r(r'.*'), lambda m: html_unescape(m[0]))

class ReportedYearToUrl(Translator):

    reported_year_url_format: str = ''

    def is_valid_url_year(self, year: int) -> bool:
        return True

    def finish(self, entry: dict[str, Any], row: dict[str, str]) -> None:
        if not entry.get('url') and self.reported_year_url_format:
            reported = entry.get('reported')
            if isinstance(reported, datetime) and self.is_valid_url_year(reported.year):
                entry['url'] = self.reported_year_url_format.format(year=reported.year)
        super().finish(entry, row)

class AK(Translator, state='AK'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        'Notes': 'action',
        'url': 'url',
    }
    rewrites = dict(
        starting=[
            ('June-August 2023', '2023-06-01'),
            ('August-November 2021', '2021-08-01'),
            ('March to May 2016', '2016-03-01'),
        ],
    )

class AL(Translator, state='AL'):
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

class AZ(Translator, state='AZ'):
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'Planned Starting Date': 'starting',
        'warn_type': 'action',
        'detail_page_url': 'url',
    }

class CA(Translator, state='CA'):
    default_url = 'https://edd.ca.gov/en/Jobs_and_Training/Layoff_Services_WARN'
    headermap = {
        'company': 'company',
        'notice_date': 'reported',
        'address': 'location',
        'num_employees': 'employees',
        'layoff_or_closure': 'action',
        'effective_date': 'starting',
        'source_file': 'url',
    }
    rewrites = dict(
        company=[
            REWRITE_UNESCAPE_HTML,
            (_r(r'\*'), ''),
            (_r(r'\n'), ' '),
            (_r(r',$'), ''),
            (_r(r'Bar- B-Que\.?'), 'Bar-B-Que'),
        ],
        starting=[
            ('03/30/3030', '2020-03-30'),
            ('03/09/2121', '2021-03-09'),
        ],
        url=[
            (_r(r'^(.+)$'), r'https://edd.ca.gov/siteassets/files/jobs_and_training/warn/\1'),
        ]
    )

class CO(Translator, state='CO'):
    default_url = 'https://cdle.colorado.gov/employers/layoff-separations/layoff-warn-list'
    headermap = {
        'company': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'jobs': 'employees',
        'occupations': 'action',
        'begin_date': 'starting'
    }
    rewrites = dict(
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('4/3020', '2020-04-30'),
            ('4/6', ''),
        ],
    )

class CT(ReportedYearToUrl, state='CT'):
    base_url = 'https://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports'
    default_url = f'{base_url}/warnreports.htm'
    reported_year_url_format = f'{base_url}/warn''{year}.htm'
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
        ]
    )

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2015

class DC(ReportedYearToUrl, state='DC'):
    base_url = 'https://does.dc.gov'
    default_url = f'{base_url}/page/rapid-response'
    reported_year_url_format = f'{base_url}/page/industry-closings-and-layoffs-warn-notifications-''{year}'
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

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2012 and year != 2014

class DE(Translator, state='DE'):
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }
class FL(ReportedYearToUrl, state='FL'):
    default_url = 'https://floridajobs.org/office-directory/division-of-workforce-services/workforce-programs/reemployment-and-emergency-assistance-coordination-team-react/warn-notices'
    reported_year_url_format = 'https://reactwarn.floridajobs.org/WarnList/viewPreviousYearsPDF?year={year}'
    headermap = {
        'Company Name': 'company',
        'State Notification Date': 'reported',
        'City': 'location',
        'Employees Affected': 'employees',
        'Notice Type': 'action',
        'Layoff Date': 'starting'
    }
    rewrites = dict(
        company=[
            (_r(r'\n.*'), ''),
        ],
    )

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2017

class GA(Translator, state='GA'):
    # TODO: reported
    default_url = 'https://www.tcsg.edu/warn-public-view/'
    headermap = {
        'Company Name': 'company',
        'Type of Layoff or Closure': 'action',
        'First Date of Separation': 'starting',
        'Number of Employees Affected': 'employees',
        'Total Number of Affected Employees': 'employees',
        'First Location Address': 'location',
        'County': 'location',
        'NAICS': 'naics'
    }
    rewrites = dict(
        location=[
            ('Sm\\', ''),
        ]
    )

class HI(Translator, state='HI'):
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

class IA(Translator, state='IA'):
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
        reported=[
            ('9/1/8/2020', '2020-09-18'),
        ],
    )

class ID(Translator, state='ID'):
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

class IL(Translator, state='IL'):
    default_url = 'https://dceo.illinois.gov/workforcedevelopment/warn.html'
    headermap = {
        'Location Name': 'company',
        'Location City': 'location',
        'Total # of Employees': 'employees',
        'Last Report Date': 'reported',
        'Initial Date Reported': 'reported',
        'Impact Date': 'starting',
        'Layoff Type': 'action',
        'NAICS Codes': 'naics'
    }
    rewrites = dict(
        company=[
            (_r(r'\*'), ''),
        ],
    )

class IN(Translator, state='IN'):
    default_url = 'https://www.in.gov/dwd/warn-notices/current-warn-notices/'
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Notice Type': 'action',
        'LO/CL Date': 'starting',
        'NAICS': 'naics'
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
    )

class KS(Translator, state='KS'):
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
            ("Walgreen's", 'Walgreens'),
        ],
    )

class KY(Translator, state='KY'):
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
        naics=[
            (_r(r'/'), ', '),
        ],
    )

class LA(ReportedYearToUrl, state='LA'):
    base_url = 'https://www.laworks.net'
    default_url = base_url
    reported_year_url_format = f'{base_url}/Downloads/WFD/WarnNotices''{year}.pdf'
    headermap = {
        'Company Name': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        # 'Industry': ...
    }
    rewrites = dict(
        starting=[
            REWRITE_COMPACT_DATERANGE,
            ('6/31/09', '2009-06-30'),
            ('5/1820', '2018-05-18'),
        ],
    )

    def is_valid_url_year(self, year: int) -> bool:
        return year >= 2007

class MD(Translator, state='MD'):
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

class ME(Translator, state='ME'):
    default_url = 'https://joblink.maine.gov/search/warn_lookups/new'
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class MI(Translator, state='MI'):
    # TODO
    headermap = {}

class MO(Translator, state='MO'):
    default_url = 'https://jobs.mo.gov/warn/'
    headermap = {
        'Title': 'company',
        'Received Sort descending': 'reported',
        'Location(s)': 'location',
        '# affected': 'employees',
        'Type': 'action',
        'Layoff date(s)': 'starting',
    }

class MT(Translator, state='MT'):
    # TODO
    headermap = {}

class NE(Translator, state='NE'):
    # TODO
    headermap = {}

class NJ(Translator, state='NJ'):
    # TODO
    headermap = {}

class NM(Translator, state='NM'):
    # TODO
    headermap = {}

class NY(Translator, state='NY'):
    default_url = 'https://dol.ny.gov/warn-notices'
    headermap = {
        'company_name': 'company',
        'Company': 'company',
        'notice_dated': 'reported',
        'Notice Date' : 'reported',
        'City': 'location',
        'date_posted': 'location',
        'Number Affected': 'employees',
        'Dislocation Type': 'action',
        'NAISC': 'naics', # sic
        'NAICS': 'naics' # in case it's fixed
    }
    rewrites = dict(
        naics=[
            ('79', ''),
        ]
    )

class OH(Translator, state='OH'):
    # TODO
    headermap = {}

class OK(Translator, state='OK'):
    default_url = 'https://okjobmatch.com/search/warn_lookups/new'
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
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

class OR(Translator, state='OR'):
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

class RI(Translator, state='RI'):
    # TODO
    headermap = {}

class SC(Translator, state='SC'):
    # TODO: reported
    default_url = 'https://scworks.org/employer/employer-programs/risk-closing/layoff-notification-reports'
    headermap = {
        'company': 'company',
        'date': 'starting',
        'location': 'location',
        'jobs': 'employees',
        'Layoff Type': 'action'
    }
    rewrites = dict(
        company=[
            (_r('Servces'), 'Services'),
            # TODO: Snake-cased names - bug in scraper?
        ],
        starting=[
            REWRITE_DOUBLE_SLASH,
            ('4/8/20/20', '2020-04-08'),
        ],
    )

class SD(Translator, state='SD'):
    # TODO
    headermap = {}

class TN(Translator, state='TN'):
    # TODO
    headermap = {}

class TX(Translator, state='TX'):
    default_url = 'https://www.twc.texas.gov/data-reports/warn-notice'
    headermap = {
        'JOB_SITE_NAME': 'company',
        'NOTICE_DATE': 'reported',
        'CITY_NAME': 'location',
        'TOTAL_LAYOFF_NUMBER': 'employees',
        'Layoff Type': 'action',
        'LayOff_Date': 'starting',
    }
    rewrites = dict(
        company=[
            (_r('_x000D_'), ''),
            # TODO: Dallas4 Plano2 etc.
        ],
        starting=[
            ('1930-03-30 00:00:00', '2020-03-30'),
            ('1930-03-31 00:00:00', '2020-03-31'),
        ],
    )

class UT(Translator, state='UT'):
    default_url = 'https://jobs.utah.gov/employer/business/warnnotices.html'
    headermap = {
        'Company Name': 'company',
        'Date of Notice': 'reported',
        'Location': 'location',
        'Affected Workers': 'employees',
        'Layoff Type': 'action',
        'Layoff Date': 'starting'
    }
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

class VA(Translator, state='VA'):
    default_url = 'https://www.vec.virginia.gov/warn-notices'
    headermap = {
        'Company Name': 'company',
        'Notice Date': 'reported',
        'Location City': 'location',
        'Employees Affected': 'employees',
        'Layoff': 'action',
        'Impact Date': 'starting'
    }
    rewrites = dict(
        starting=[
            ('10/01/1973', '2020-10-01'),
        ],
    )

class VT(Translator, state='VT'):
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

class WA(Translator, state='WA'):
    # TODO
    headermap = {}

class WI(Translator, state='WI'):
    default_url = 'https://dwd.wisconsin.gov/dislocatedworker/warn/'
    headermap = {
        'Company': 'company',
        'Notice Received': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Original Notice Type / Update Type': 'action',
        'Layoff Begin Date': 'starting'
    }
    rewrites = dict(
        company=[
            (_r(r'\s*\(CORRECTED\)$'), ''),
        ],
    )


class ReviewTable:

    def __init__(self, state: str, field: str, empty: bool = False):
        self.state = state.upper()
        self.field = field
        self.empty = empty
        self.translator = translators[self.state]()
        self.headermap = self.translator.headermap
        self.columns = []
        for header, fields in self.headermap.items():
            if isinstance(fields, str):
                fields = [fields]
            for field in fields:
                if field == self.field:
                    self.columns.append(header)

    def rows(self):
        file = utils.Stage.Extract.file(self.state)
        it = map(self.values, utils.csvdicts(file))
        if not self.empty:
            it = filter(any, map(list, it))
        for values in it:
            yield [self.state, *values]

    def headers(self):
        yield 'state'
        yield self.field
        yield from self.columns

    def values(self, row: dict):
        yield self.translator.entry(row).get(self.field)
        yield from map(row.get, self.columns)

class Command(utils.BaseCommand):
    """
    Print values & translations for given field/header.
    """

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            'field',
            help='The field name')
        parser.add_argument(
            'states',
            nargs='*',
            metavar='states',
            choices=translators)
        parser.add_argument(
            '--empty', '-e',
            action='store_true',
            help='Include empty values')
        parser.add_argument(
            '--sort', '-o',
            action='store_true',
            help='Sort')

    def setup(self, opts):
        self.tables = [
            ReviewTable(state, opts.field, opts.empty)
            for state in opts.states or translators]

    def run(self):
        import tabulate
        for table in self.tables:
            rows = table.rows()
            if self.opts.sort:
                rows = sorted(rows)
            print(tabulate.tabulate(rows, table.headers()))

if __name__ == '__main__':
    try:
        Command.main()
    except BrokenPipeError:
        pass
