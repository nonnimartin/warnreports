from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from contextlib import (AbstractAsyncContextManager, AbstractContextManager,
                        asynccontextmanager)
from typing import (Any, AsyncIterable, AsyncIterator, Callable, ClassVar,
                    Iterable, Mapping, Sequence)

type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type EitherContext[T] = AbstractContextManager[T]|AbstractAsyncContextManager[T]


async def wait(ret):
    return await ret if asyncio.iscoroutine(ret) else ret

def as_aiter[T](it: EitherIterable[T]) -> AsyncIterable[T]:
    return it if isinstance(it, AsyncIterable) else _to_aiter(it)

async def _to_aiter[T](it: Iterable[T]) -> AsyncIterator[T]:
    for x in it:
        yield x

async def aenumerate[T](it: EitherIterable[T]) -> AsyncIterator[tuple[int, T]]:
    i = 0
    async for x in as_aiter(it):
        yield i, x
        i += 1

async def amap[T, R](func: Callable[[T], R], it: EitherIterable[T]) -> AsyncIterator[R]:
    async for x in as_aiter(it):
        yield await wait(func(x))

async def astarmap[**P, R](func: Callable[P, R], it: EitherIterable[P]) -> AsyncIterator[R]:
    async for args in as_aiter(it):
        yield await wait(func(*args))

@asynccontextmanager
async def awith[T](ctx: EitherContext[T]):
    if isinstance(ctx, AbstractAsyncContextManager):
        async with ctx as it:
            yield it
    else:
        with ctx as it:
            yield it

async def achain_from_iterable[T](it: EitherIterable[EitherIterable[T]]) -> AsyncIterator[T]:
    async for it in as_aiter(it):
        async for x in as_aiter(it):
            yield x

@dataclasses.dataclass(frozen=True, kw_only=True)
class Wait[T]:
    'Async retry/wait parameters'
    timeout: float = 0.0
    'The total time limit'
    poll: float = 0.5
    'Time to wait in between poll'
    ignored: type[Exception]|tuple[type[Exception], ...] = ()
    'Exception types to ignore'
    args: Sequence[Any] = ()
    'Args to pass to the callback'
    kwargs: Mapping = dataclasses.field(default_factory=dict)
    'Kwargs to pass to the callback'
    raises: type[Exception] = dataclasses.field(default_factory=lambda: TimeoutError)
    'The exception class to raise on timeout, default TimeoutError'
    oper: Callable[[Any], Any] = dataclasses.field(default_factory=lambda: bool)
    'The operator to apply to the result of the callback to test for truthiness, default bool'
    callback: Callable[..., T] = dataclasses.field(default_factory=lambda: type(None))
    'The callback function'
    logger: ClassVar = logging.getLogger(f'{__name__}.wait')

    async def until[T](self, callback: Callable[..., T], /, **kw) -> T:
        return await self(callback=callback, **kw)

    async def __call__(self, **kw) -> T:
        'Wait until the callback returns a truthy value'
        inst = self.replace(**kw) if kw else self
        end = time.monotonic() + inst.timeout
        err = None
        if isinstance(inst.ignored, type):
            ignored = (inst.ignored,)
        else:
            ignored = tuple(inst.ignored or ())
        while True:
            try:
                value = await wait(inst.callback(*inst.args, **inst.kwargs))
                if inst.oper(value):
                    return value
            except ignored as exc:
                err = exc
            if time.monotonic() > end:
                break
            self.logger.debug(f'Retrying in {inst.poll}s {inst.callback.__name__}')
            await asyncio.sleep(inst.poll)
        raise inst.raises from err

    replace = dataclasses.replace