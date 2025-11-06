from aioflux.queues.base.base import BaseQueue
from aioflux.core.metrics import incr, gauge
from typing import Any, Optional, Callable, Set
import asyncio
import hashlib


class DedupeQueue(BaseQueue):
    """
    Очередь с дедупликацией (Dedupe Queue).

    Сохраняет элементы только если их еще не было в очереди
    в течение заданного TTL.

    Полезна для задач, где одно и то же действие может быть запрошено
    многократно, но выполнять его нужно лишь раз (например, индексация или уведомления).
    """

    def __init__(
        self,
        workers: int = 1,
        max_size: int = 10000,
        ttl: float = 300.0,
        key_fn: Optional[Callable[[Any], str]] = None
    ):
        """
        workers — количество воркеров
        max_size — максимальный размер очереди
        ttl — сколько секунд хранить ключ в `_seen`
        key_fn — функция генерации ключа для элемента
        """
        self.workers = workers
        self.max_size = max_size
        self.ttl = ttl
        self.key_fn = key_fn or self._default_key

        self._queue = asyncio.Queue(maxsize=max_size)
        self._seen: Set[str] = set()
        self._tasks = []
        self._running = False
        self._lock = asyncio.Lock()

    def _default_key(self, item: Any) -> str:
        data = str(item).encode()
        return hashlib.md5(data).hexdigest()

    async def put(self, item: Any, priority: int = 0) -> None:
        """
        Добавляет элемент в очередь, если его ещё не было.
        Если элемент уже присутствует — пропускается.
        """
        key = self.key_fn(item)

        async with self._lock:
            if key in self._seen:
                await incr("queue.dedupe.duplicates")
                return

            self._seen.add(key)
            await self._queue.put((key, item))
            await incr("queue.dedupe.put")
            await gauge("queue.dedupe.size", self._queue.qsize())

            asyncio.create_task(self._expire_key(key))

    async def get(self) -> Any:
        key, item = await self._queue.get()
        await incr("queue.dedupe.get")
        await gauge("queue.dedupe.size", self._queue.qsize())
        return item

    async def size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._worker(i))
            for i in range(self.workers)
        ]

    async def stop(self) -> None:
        self._running = False
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _worker(self, worker_id: int) -> None:
        """
        Цикл воркера:
        - достаёт элемент
        - выполняет его (callable / coroutine / coroutine function)
        """
        while self._running:
            try:
                item = await asyncio.wait_for(self.get(), timeout=1.0)

                if asyncio.iscoroutine(item):
                    await item
                elif asyncio.iscoroutinefunction(item):
                    await item()
                elif callable(item):
                    result = item()
                    if asyncio.iscoroutine(result):
                        await result

                await incr(f"queue.dedupe.worker.{worker_id}.processed")

            except asyncio.TimeoutError:
                continue
            except Exception:
                await incr(f"queue.dedupe.worker.{worker_id}.errors")

    async def _expire_key(self, key: str) -> None:
        """
        Удаляет ключ из `_seen` по истечении TTL,
        чтобы элементы могли снова попасть в очередь.
        """
        await asyncio.sleep(self.ttl)
        async with self._lock:
            self._seen.discard(key)
