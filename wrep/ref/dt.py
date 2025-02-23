from __future__ import annotations

import re

txt = """
    january
    february
    march
    april
    may
    june
    july
    august
    september
    october
    november
    december"""

MONTHNAME_REWRITES = tuple(zip(
    (re.compile(x, re.I) for x in txt.split()),
    (str(x).zfill(2) for x in range(1, 13))))