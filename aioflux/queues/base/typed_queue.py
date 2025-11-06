from abc import abstractmethod
from typing import Callable, Generic, Optional, Protocol, TypeVar

from aioflux.queues.dedupe import DedupeQueue
from aioflux.queues.base.base import BaseQueue


T = TypeVar('T')
R = TypeVar('R')


class Handler(Protocol[T, R]):
    async def __call__(self, item: T) -> R: ...


class TypedQueue(BaseQueue, Generic[T]):
    @abstractmethod
    async def put(self, item: T, priority: int = 0) -> None: ...

    @abstractmethod
    async def get(self) -> T: ...


class TypedDedupeQueue(TypedQueue[T], Generic[T]):
    def __init__(
        self,
        workers: int = 1,
        max_size: int = 10000,
        ttl: float = 300.0,
        key_fn: Optional[Callable[[T], str]] = None
    ):
        self._queue = DedupeQueue(workers, max_size, ttl, key_fn)

    async def put(self, item: T, priority: int = 0) -> None:
        await self._queue.put(item, priority)

    async def get(self) -> T:
        return await self._queue.get()

    async def size(self) -> int:
        return await self._queue.size()

    async def start(self) -> None:
        await self._queue.start()

    async def stop(self) -> None:
        await self._queue.stop()
