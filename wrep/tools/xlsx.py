from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook as load_workbook
from openpyxl.worksheet.worksheet import Worksheet


def extract_workbook(file: Path) -> Iterator[dict[str, str]]:
    worksheet = load_workbook(file, read_only=True).worksheets[0]
    return extract_worksheet(worksheet)

def extract_worksheet(ws: Worksheet) -> Iterator[dict[str, str]]:
    it = ([cell.value for cell in row] for row in ws.rows)
    headers = next(it)
    for values in filter(any, it):
        row = {}
        for k, v in filter(any, zip(headers, values)):
            if v is None:
                v = ''
            elif isinstance(v, datetime):
                v = v.strftime(f'%Y-%m-%d')
            else:
                v = str(v)
            row[k] = v
        yield row