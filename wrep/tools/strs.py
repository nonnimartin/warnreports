from __future__ import annotations

from uuid import UUID, uuid5

from .. import settings

__all__ = ['struuid']

STRNS = uuid5(settings.NAMESPACE, 'tools.strs')

def struuid(value: str) -> UUID:
    return uuid5(STRNS, value)