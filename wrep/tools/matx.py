from __future__ import annotations

from ..utils import morethan
import math

def nonempty_columns(arr: list[list]) -> list[list]:
    """
    +---+---+---+---+       +---+---+---+
    | x |   |   | x |       | x |   | x |
    +---+---+---+---+  =>   +---+---+---+
    |   | x |   | x |       |   | x | x |
    +---+---+---+---+       +---+---+---+
    """
    if not arr:
        return arr
    cols = [
        c for c in range(len(arr[0]))
        if any(row[c] for row in arr)]
    return [[row[c] for c in cols] for row in arr]

def nonsparse_rows(arr: list[list], /, *, threshold: int = 2) -> list[list]:
    if not arr:
        return arr
    return [row for row in arr if morethan(threshold, row)]

def align_columns(arr: list[list], /, *, tolerance: float = 0.9) -> None:
    """
    +---+---+      +---+
    | x |   |      | x |
    +---+---+  =>  +---+
    |   | x |      | x |
    +---+---+      +---+
    """
    length = len(arr)
    if length < 2:
        return arr
    tolerance = float(max(0, min(1, tolerance)))
    def most(it):
        return morethan(tolerance * length, it)
    c = 0
    while c <= len(arr[0]) - 2:
        d = c + 1
        realign = (
            most(row[c] or row[d] for row in arr) and
            not any(row[c] and row[d] for row in arr))
        if realign:
            for row in arr:
                if not row[c]:
                    del row[c]
                else:
                    del row[d]
        c += 1