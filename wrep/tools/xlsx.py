from __future__ import annotations

from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Iterator

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet


@wraps(openpyxl.load_workbook)
def load_workbook(file: Path, read_only=True, **kw):
    return openpyxl.load_workbook(file, read_only=read_only, **kw)

def extract_workbook(file: Path, **kw) -> Iterator[dict[str, str]]:
    ws = load_workbook(file, **kw).worksheets[0]
    return extract_worksheet(ws)

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