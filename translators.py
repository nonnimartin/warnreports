from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import utils
from models import HttpUrl, ValidationError

PAT_SPACES = re.compile(r'\s+')
translators: dict[str, type[Translator]] = {}

class Translator:

    registry = {}
    headermap = {}

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
        method = f'value_{field}'
        if hasattr(self, method):
            value = getattr(self, method)(value)
        return value

    def value_reported(self, value: str) -> datetime|None:
        return self.parse_date(value)

    def value_starting(self, value: str) -> datetime|None:
        return self.parse_date(value)

    def value_employees(self, value: str) -> int|None:
        return utils.parse_int(value)

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

    def value_naics(self, value: str) -> str|None:
        value = utils.parse_int(value)
        if value and 2 <= len(str(value)) <= 6:
            return value

    def sanitize(self, value: str) -> str:
        return value.strip()

    def parse_date(self, value: str) -> datetime|None:
        return utils.parse_date(value)

    def __init_subclass__(cls, state: str|None = None) -> None:
        if state:
            translators[state.upper()] = cls

class AK(Translator, state='AK'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Employees Affected': 'employees',
        'Layoff Date': 'starting',
        'Notes': 'action'
    }

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

class CO(Translator, state='CO'):
    headermap = {
        'company': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'jobs': 'employees',
        'occupations': 'action',
        'begin_date': 'starting'
    }

class CT(Translator, state='CT'):
    headermap = {
        'affected_company': 'company',
        'warn_date': 'reported',
        'layoff_location': 'location',
        'number_workers': 'employees',
        'closing': 'action',
        'layoff_date': 'starting'
    }

    def value_company(self, value: str) -> str:
        value = value.replace('*', '').strip()
        return super().value_company(value)

    def value_reported(self, value: str) -> datetime|None:
        it = map(self.parse_date, value.split(' '))
        return max(filter(None, it), default=None)

class DC(Translator, state='DC'):
    headermap = {
        'Organization Name': 'company',
        'Notice Date': 'reported',
        'city': 'location',
        'Number toEmployees Affected': 'employees',
        'layoff_or_closure': 'action',
        'Effective Layoff Date': 'starting'
    }

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

    def parse_date(self, value: str) -> datetime|None:
        value = value.split('\n')[0].strip()
        return super().parse_date(value)

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
        'LO/CL Date': 'starting',
        'PDF url': 'url'
    }

class IA(Translator, state='IA'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'City': 'location',
        'Emp #': 'employees',
        'Notice Type': 'action',
        'Layoff Date': 'starting'
    }

class ID(Translator, state='ID'):
    headermap = {
        'Company': 'company',
        'Date of Letter': 'reported',
        'City': 'location',
        'No. of Employees Affected': 'employees',
        'Effective or Commencing Date': 'starting'
    }

    def value_reported(self, value: str) -> datetime|None:
        """
        2/18/22 (rec'd 3/21/22)
        4/29/2020 (Rec'd 5/5/2020)
        2/19/219 (rec'd 2/26/19)
        1/6/2016 (revised thru 5/5/16)
        4/1/2020 - REVISED 4/8/2020
        3/31/2020 (rec' 4/1/2020)
        4/3/2020, 4/15/2020, & 5/1/2020
        """
        dt = self.parse_date(value)
        if dt:
            return dt
        value = re.sub(r'[^\d/ ]', '', value)
        it = map(self.parse_date, PAT_SPACES.split(value))
        return max(filter(None, it), default=None)

    def value_company(self, value: str) -> str:
        """
        D e n n y ' s
        """
        if value.lower() == "D e n n y ' s".lower():
            value = value.replace(' ', '')
        return super().value_company(value)

    def value_employees(self, value: str) -> int|None:
        """
        120 (2 in ID)
        """
        return utils.parse_int(value.split(' ')[0])

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
        'LO/CL Date': 'starting'
    }

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

class MD(Translator, state='MD'):
    headermap = {
        'Company': 'company',
        'Notice Date': 'reported',
        'Location': 'location',
        'Total Employees': 'employees',
        'Type': 'action',
        'Effective Date': 'starting'
    }

class ME(Translator, state='ME'):
    headermap = {
        'employer': 'company',
        'notice_date': 'reported',
        'city': 'location',
        'number_of_employees_affected': 'employees',
        'warn_type': 'action',
        'detail_page_url': 'url'
    }

class MO(Translator, state='MO'):
    headermap = {
        'Title': 'company',
        'Received Sort descending': 'reported',
        'Location(s)': 'location',
        '# affected': 'employees',
        'Type': 'action',
        'Layoff date(s)': 'starting'
    }

class NY(Translator, state='NY'):
    headermap = {
        'company_name': 'company',
        'Company': 'company',
        'notice_dated': 'reported',
        'Notice Date' : 'reported',
        'City': 'location',
        'date_posted': 'location',
        'Number Affected': 'employees',
        'Dislocation Type': 'action'
    }

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

class SC(Translator, state='SC'):
    headermap = {
        'company': 'company',
        'date': 'starting',
        'location': 'location',
        'jobs': 'employees',
        'Layoff Type': 'action'
    }

class TX(Translator, state='TX'):
    headermap = {
        'JOB_SITE_NAME': 'company',
        'NOTICE_DATE': 'reported',
        'CITY_NAME': 'location',
        'TOTAL_LAYOFF_NUMBER': 'employees',
        'Layoff Type': 'action',
        'LayOff_Date': 'starting'
    }

class UT(Translator, state='UT'):
    headermap = {
        'Company Name': 'company',
        'Date of Notice': 'reported',
        'Location': 'location',
        'Affected Workers': 'employees',
        'Layoff Type': 'action',
        'Layoff Date': 'starting'
    }

class VA(Translator, state='VA'):
    headermap = {
        'Company Name': 'company',
        'Notice Date': 'reported',
        'Location City': 'location',
        'Employees Affected': 'employees',
        'Layoff': 'action',
        'Impact Date': 'starting'
    }

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

class WI(Translator, state='WI'):
    headermap = {
        'Company': 'company',
        'Notice Received': 'reported',
        'City': 'location',
        'Affected Workers': 'employees',
        'Original Notice Type / Update Type': 'action',
        'Layoff Begin Date': 'starting'
    }
