from __future__ import annotations

from typing import Iterable, Iterator, Sequence

from ..utils import morethan


def nonempty_columns[T](arr: Sequence[Sequence[T]]) -> list[list[T]]:
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

def nonsparse_rows[S: Sequence](arr: Sequence[S], /, *, threshold: int = 2) -> list[S]:
    if not arr:
        return arr
    return [row for row in arr if morethan(threshold, row)]

def align_columns(arr: Sequence[list], /, *, tolerance: float = 0.9) -> None:
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

def merge_tables[T, L: Sequence[T]](arrs: Iterable[Sequence[L]]) -> Iterator[L]:
    """
    Flattten tables, using the first row of the first table as the header.
    If the first row of subsequent tables matches the initial header row,
    it is skipped.
    """
    width, head = None, None
    for i, table in enumerate(arrs):
        h = table[0]
        w = len(h)
        if i == 0:
            width, head = w, h
        elif width != w:
            raise ValueError(f'Mismatched table widths {width}, {w}')
        elif head == h:
            table = iter(table)
            next(table)
        yield from table

