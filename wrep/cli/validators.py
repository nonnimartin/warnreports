from __future__ import annotations

from typing import Annotated, Any, Iterable

from pydantic import BeforeValidator, Field, TypeAdapter

from .. import Stage
from ..models import StateCode

StatesOpt = Annotated[
    list[StateCode],
    BeforeValidator(lambda x: resolve_statesopt(x)),
    Field(
        min_length=1,
        description=(
            'Optionally specify states as additional arguments. '
            'If not specified, include all states. To exclude a '
            'state, prefix with ^'))]
StagesOpt = Annotated[
    list[Stage],
    BeforeValidator(lambda x: resolve_stagesopt(x)),
    Field(min_length=1, description='Stage name(s) (various formats) or "all"')]
StatesOptTa = TypeAdapter(StatesOpt)

def resolve_statesopt(value: Iterable[StateCode]) -> list[StateCode]:
    from ..translators import TranslationFactory
    allstates = TranslationFactory.translators
    states: set[StateCode] = set()
    skips: set[StateCode] = set()
    for opt in map(str.upper, value):
        if opt.startswith('^'):
            skips.add(opt[1:])
        else:
            states.add(opt)
    if not states:
        states.update(allstates)
    states.difference_update(skips)
    bad = states.difference(allstates)
    if bad:
        raise ValueError(f'Invalid states: {sorted(bad)}')
    return sorted(states)

def resolve_stagesopt(value: str|Stage|Iterable[str|Stage]|Any) -> list[Stage]:
    if not isinstance(value, str):
        if isinstance(value, Iterable):
            value = ' '.join(map(str, value))
        else:
            value = str(value)
    if value == 'all':
        return list(Stage)
    value = value.replace(',', ' ')
    for stage in Stage:
        value = value.replace(stage[0].upper(), f' {stage.value} ')
    trans = {stage[0]: stage for stage in Stage}
    return [Stage(trans.get(value, value)) for value in value.split()]
