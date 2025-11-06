import asyncio
from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Any

from aioflux.utils.common import now
from aioflux.queues.base.base import BaseQueue
from aioflux.core.metrics import gauge, incr


@dataclass(order=True)
class DelayedItem:
    """Элемент с временем выполнения (используется в min-heap)."""
    execute_at: float
    item: Any = field(compare=False)


class DelayQueue(BaseQueue):
    """
    Очередь с отложенным выполнением (Delay Queue).

    Особенности:
    - элементы извлекаются только после наступления их времени execute_at
    - реализована на min-heap (через heapq)
    - поддерживает несколько воркеров
    """

    def __init__(self, workers: int = 1, max_size: int = 10000):
        """
        workers — количество воркеров
        max_size — максимум элементов в очереди
        """
        self.workers = workers
        self.max_size = max_size

        self._queue = []
        self._tasks = []
        self._running = False
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)

    async def put(self, item: Any, delay: float = 0, priority: int = 0) -> None:
        """
        Добавляет задачу с задержкой `delay` секунд.
        Элементы хранятся в порядке ближайшего времени исполнения.
        """
        async with self._lock:
            if len(self._queue) >= self.max_size:
                raise asyncio.QueueFull()

            execute_at = now() + delay
            heappush(self._queue, DelayedItem(execute_at, item))
            await incr("queue.delay.put")
            await gauge("queue.delay.size", len(self._queue))
            # разбудим воркеров, если очередь не пуста
            self._not_empty.notify()

    async def get(self) -> Any:
        """
        Возвращает элемент, когда пришло его время исполнения.
        Если очередь пуста или время не настало — ждёт.
        """
        async with self._not_empty:
            while True:
                if not self._queue:
                    await self._not_empty.wait()
                    continue

                item = self._queue[0]
                current = now()

                if item.execute_at <= current:
                    heappop(self._queue)
                    await incr("queue.delay.get")
                    await gauge("queue.delay.size", len(self._queue))
                    return item.item

                wait_time = item.execute_at - current
                try:
                    await asyncio.wait_for(self._not_empty.wait(), timeout=wait_time)
                except asyncio.TimeoutError:
                    continue

    async def size(self) -> int:
        async with self._lock:
            return len(self._queue)

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._worker(i))
            for i in range(self.workers)
        ]

    async def stop(self) -> None:
        self._running = False
        async with self._not_empty:
            self._not_empty.notify_all()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _worker(self, worker_id: int) -> None:
        """
        Цикл воркера:
        - ждёт задачи с истёкшей задержкой
        - исполняет callable / coroutine / coroutine function
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

                await incr(f"queue.delay.worker.{worker_id}.processed")

            except asyncio.TimeoutError:
                continue
            except Exception:
                await incr(f"queue.delay.worker.{worker_id}.errors")
