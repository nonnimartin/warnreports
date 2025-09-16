from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections import deque
from contextlib import (AbstractAsyncContextManager, AbstractContextManager,
                        asynccontextmanager)
from typing import (Any, AsyncIterable, AsyncIterator, Callable, ClassVar,
                    Coroutine, Iterable, Mapping, Sequence)

from pydantic import NonNegativeFloat, PositiveInt

type EitherIterable[T] = Iterable[T]|AsyncIterable[T]
type EitherContext[T] = AbstractContextManager[T]|AbstractAsyncContextManager[T]

async def wait[T](ret: T|Coroutine[Any, Any, T]) -> T:
    "Await if necessary, then return the result"
    return await ret if asyncio.iscoroutine(ret) else ret

def as_aiter[T](it: EitherIterable[T]) -> AsyncIterable[T]:
    "Convert an iterable into an async iterable if it is not already"
    return it if isinstance(it, AsyncIterable) else _to_aiter(it)

async def _to_aiter[T](it: Iterable[T]) -> AsyncIterator[T]:
    for x in it:
        yield x

async def aenumerate[T](it: EitherIterable[T], start: int = 0) -> AsyncIterator[tuple[int, T]]:
    "Async version of enumerate(). Supports both async and regular iterables"
    i = start
    async for x in as_aiter(it):
        yield i, x
        i += 1

async def amap[T, R](func: Callable[[T], R], it: EitherIterable[T]) -> AsyncIterator[R]:
    "Async version of map(). Supports both async and regular iterables and functions"
    async for x in as_aiter(it):
        yield await wait(func(x))

async def astarmap[**P, R](func: Callable[P, R], it: EitherIterable[P]) -> AsyncIterator[R]:
    "Async version of itertools.starmap(). Supports both async and regular iterables and functions"
    async for args in as_aiter(it):
        yield await wait(func(*args))

@asynccontextmanager
async def awith[T](ctx: EitherContext[T]):
    "Convert a context manager into an async context manager if it is not already"
    if isinstance(ctx, AbstractAsyncContextManager):
        async with ctx as it:
            yield it
    else:
        with ctx as it:
            yield it

async def achain_from_iterable[T](it: EitherIterable[EitherIterable[T]]) -> AsyncIterator[T]:
    "Async version of itertools.chain.from_iterable(). Supports both async and regular iterables"
    async for it in as_aiter(it):
        async for x in as_aiter(it):
            yield x

@dataclasses.dataclass(frozen=True, kw_only=True)
class Wait[T]:
    """
    Async retry/wait parameters.
    
    Examples::
    
    >>> wait = Wait()
    >>> await wait(callback=myfunc, timeout=5)

    With defaults::

    >>> wait = Wait(timeout=5.0, ignored=ValueError, poll=0.1)
    >>> await wait(callback=myfunc, args=[1, 2], kwargs=dict(myarg='value'))
    """
    timeout: NonNegativeFloat = 0.0
    'The total time limit'
    poll: NonNegativeFloat = 0.5
    'Time to wait in between poll'
    ignored: type[Exception]|Sequence[type[Exception]] = ()
    'Exception types to ignore'
    args: Sequence[Any] = ()
    'Args to pass to the callback'
    kwargs: Mapping = dataclasses.field(default_factory=dict)
    'Kwargs to pass to the callback'
    raises: type[Exception] = dataclasses.field(default_factory=lambda: TimeoutError)
    'The exception class to raise on timeout, default TimeoutError'
    oper: Callable[[Any], Any] = dataclasses.field(default_factory=lambda: bool)
    'The operator to apply to the result of the callback to test for truthiness, default bool'
    callback: Callable[..., T|Coroutine[Any, Any, T]] = dataclasses.field(default_factory=lambda: type(None))
    'The callback function, supports async or regular functions'
    logger: ClassVar = logging.getLogger(f'{__name__}.wait')

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

    async def until[T](self, callback: Callable[..., T], /, **kw) -> T:
        'Accepts callback as first parameter'
        return await self(callback=callback, **kw)

    replace = dataclasses.replace

async def pooled[T, R](it: EitherIterable[T], /, target: Callable[[T], R|Coroutine[Any, Any, R]], *, size: PositiveInt = 1) -> tuple[R, ...]:
    """
    Create an async worker pool of a given size and return the awaited results
    """
    queue = deque()
    async for x in as_aiter(it):
        queue.append(x)
    results: deque[R] = deque()

    async def worker():
        while True:
            try:
                arg = queue.popleft()
            except IndexError:
                break
            results.append(await wait(target(arg)))

    async with asyncio.TaskGroup() as group:
        for _ in range(min(size, len(queue))):
            group.create_task(worker())
    return tuple(results)
