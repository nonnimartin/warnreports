from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import utils
from .models import HttpUrl, State, ValidationError

PAT_SPACES = re.compile(r'\s+')
PAT_NONDIGITS = re.compile(r'[^\d]+')
logger = utils.get_logger('translators')
translators: dict[State, type[Translator]] = {}

_r = re.compile

class Translator:

    headermap: dict[str, str] = {}
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
        for header, field in self.headermap.items():
            if header not in row or field in entry:
                continue
            value = self.value(field, row[header])
            if value:
                entry[field] = value
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
        value = value.split('\n')[0].strip()
        value = PAT_SPACES.sub(' ', value)
        return value

    def value_action(self, value: str) -> str:
        return value.strip('*').strip()

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
        return value.strip()

    def rewrite(self, field: str, value: str) -> str:
        if field in self.rewrites:
            for srch, repl in self.rewrites[field]:
                if srch == value:
                    value = repl
                elif isinstance(srch, re.Pattern):
                    value = srch.sub(repl, value)
        return value

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

class AK(Translator, state='AK'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        'Notes': 'action'
    }
    rewrites = dict(
        starting=[
            ('June-August 2023', '2023-06-01'),
            ('August-November 2021', '2021-08-01'),
            ('March to May 2016', '2016-03-01'),
        ],
    )

class AL(Translator, state='AL'):
    headermap = {
        'Company': 'company',
        'Initial Report Date': 'reported',
        'City': 'location',
        'Planned # Affected Employees': 'employees',
        'Closing or Layoff': 'action',
        'Planned Starting Date': 'starting'
    }

class AZ(Translator, state='AZ'):
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'Planned Starting Date': 'starting',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class CA(Translator, state='CA'):
    headermap = {
        'company': 'company',
        'notice_date': 'reported',
        'address': 'location',
        'num_employees': 'employees',
        'layoff_or_closure': 'action',
        'effective_date': 'starting'
    }
    rewrites = dict(
        starting=[
            ('03/30/3030', '2020-03-30'),
            ('03/09/2121', '2021-03-09'),
        ],
    )

class CO(Translator, state='CO'):
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

class CT(Translator, state='CT'):
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
    )

class DC(Translator, state='DC'):
    headermap = {
        'Organization Name': 'company',
        'Notice Date': 'reported',
        'city': 'location',
        'Number toEmployees Affected': 'employees',
        'layoff_or_closure': 'action',
        'Effective Layoff Date': 'starting'
    }
    rewrites = dict(
        reported=[
            ('May 2 and 5, 2020', '2020-05-05'),
            ('May 7,14 & 31, 2012', '2012-05-31'),
            ('31, 2019', ''),
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
    )

class DE(Translator, state='DE'):
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class FL(Translator, state='FL'):
    headermap = {
        'Company Name': 'company',
        'State Notification Date': 'reported',
        'City': 'location',
        'Employees Affected': 'employees',
        'Notice Type': 'action',
        'Layoff Date': 'starting'
    }

class GA(Translator, state='GA'):
    # TODO: reported
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

class HI(Translator, state='HI'):
    headermap = {
        'Company': 'company',
        'Date': 'reported',
        'location': 'location',
        'jobs': 'employees',
        'Notice Type': 'action',
        # TODO: no data
        'LO/CL Date': 'starting',
        'PDF url': 'url'
    }
    rewrites = dict(
        reported=[
            (_r(r'#\d+'), ''),
        ],
    )

class IA(Translator, state='IA'):
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

class IN(Translator, state='IN'):
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
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'LO/CL Date': 'starting',
        'detail_page_url': 'url'
    }

class KY(Translator, state='KY'):
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

class LA(Translator, state='LA'):
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

class MD(Translator, state='MD'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Total Employees': 'employees',
        'Type': 'action',
        'Effective Date': 'starting'
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
        employees=[
            *Translator.rewrites['employees'],
            (_r(r'December 2013$'), ''),
        ]
    )

class ME(Translator, state='ME'):
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
    headermap = {
        'Title': 'company',
        'Received Sort descending': 'reported',
        'Location(s)': 'location',
        '# affected': 'employees',
        'Type': 'action',
        'Layoff date(s)': 'starting',
        'NAICS Code': 'naics'
    }
    rewrites = dict(
        reported=[
            ('3/3020/17', '2017-03-30'),
            ('5/62011', '2011-05-06'),
        ]
    )

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
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class OR(Translator, state='OR'):
    headermap = {
        'Company Name': 'company',
        'Received Date': 'reported',
        'Location': 'location',
        'Laid Off': 'employees',
        'Layoff Type': 'action',
        'Layoff Date': 'starting'
    }

class RI(Translator, state='RI'):
    # TODO
    headermap = {}

class SC(Translator, state='SC'):
    # TODO: reported
    headermap = {
        'company': 'company',
        'date': 'starting',
        'location': 'location',
        'jobs': 'employees',
        'Layoff Type': 'action'
    }
    rewrites = dict(
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
    headermap = {
        'JOB_SITE_NAME': 'company',
        'NOTICE_DATE': 'reported',
        'CITY_NAME': 'location',
        'TOTAL_LAYOFF_NUMBER': 'employees',
        'Layoff Type': 'action',
        'LayOff_Date': 'starting'
    }
    rewrites = dict(
        starting=[
            ('1930-03-30 00:00:00', '2020-03-30'),
            ('1930-03-31 00:00:00', '2020-03-31'),
        ],
    )

class UT(Translator, state='UT'):
    headermap = {
        'Company Name': 'company',
        'Date of Notice': 'reported',
        'Location': 'location',
        'Affected Workers': 'employees',
        'Layoff Type': 'action',
        'Layoff Date': 'starting'
    }
    rewrites = dict(
        reported=[
            REWRITE_DOUBLE_SLASH,
            ('09/31/10', '2010-09-30'),
            ('05/2009', '2009-05-01'),
        ],
    )

class VA(Translator, state='VA'):
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
    headermap = {
        'Company': 'company',
        'Notice Received': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Original Notice Type / Update Type': 'action',
        'Layoff Begin Date': 'starting'
    }


class ReviewTable:

    def __init__(self, state: State, field: str, empty: bool = False):
        self.state = state.upper()
        self.field = field
        self.empty = empty
        self.translator = translators[self.state]()
        self.headermap = self.translator.headermap
        self.columns = []
        for header, field in self.headermap.items():
            if field == self.field:
                self.columns.append(header)

    def rows(self):
        from .pipeline import Stage
        file = Stage.Extract.file(self.state)
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

    def validate(self):
        for header in self.columns:
            if header not in self.headermap:
                raise ValueError(f'Unknown {header=}')
        if self.field not in self.headermap.values():
            raise ValueError(f'Unknown field={self.field}')

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

    def setup(self, opts):
        self.tables = [
            ReviewTable(state, opts.field, opts.empty)
            for state in opts.states or translators]
        self.errors = {}
        for table in self.tables:
            try:
                table.validate()
            except ValueError as err:
                self.errors[table.state] = f'{table.state}: {err}'

    def run(self):
        import tabulate
        for table in self.tables:
            if table.state in self.errors:
                print(f'ERROR: {self.errors[table.state]}')
            else:
                print(tabulate.tabulate(table.rows(), table.headers()))
        if len(self.errors) == len(self.tables):
            raise Exception(f'No valid tables to print')

if __name__ == '__main__':
    try:
        Command.main()
    except BrokenPipeError:
        pass
