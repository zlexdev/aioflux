import asyncio
from dataclasses import dataclass, field
from heapq import heappop, heappush
from time import time
from typing import Any, Callable, Optional

from aioflux.queues.base.base import BaseQueue
from aioflux.core.metrics import gauge, incr, Timer


@dataclass(order=True)
class PriorityItem:
    """
    Элемент очереди с приоритетом.
    Чем выше `priority`, тем раньше он обрабатывается.
    """
    priority: int
    item: Any = field(compare=False)
    timestamp: float = field(compare=False)


class PriorityQueue(BaseQueue):
    """
    Очередь с приоритетом (Priority Queue).

    Элементы хранятся в куче (heap) и извлекаются в порядке убывания приоритета.
    Поддерживает ограничение размера, несколько воркеров и метрики.
    """

    def __init__(
        self,
        workers: int = 1,
        max_size: int = 10000,
        priority_fn: Optional[Callable[[Any], int]] = None
    ):
        """
        workers — количество воркеров
        max_size — максимальный размер очереди
        priority_fn — функция вычисления приоритета (если не задан явно)
        """
        self.workers = workers
        self.max_size = max_size
        self.priority_fn = priority_fn or (lambda x: 0)

        self._queue = []
        self._tasks = []
        self._running = False
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)
        self._not_full = asyncio.Condition(self._lock)
        self._counter = 0  # счетчик вставок (для отладки/метрик)

    async def put(self, item: Any, priority: Optional[int] = None) -> None:
        """
        Добавляет элемент в очередь.
        Если очередь заполнена — ждет, пока освободится место.
        """
        async with self._not_full:
            while len(self._queue) >= self.max_size:
                await self._not_full.wait()

            if priority is None:
                priority = self.priority_fn(item)

            # используем отрицательный приоритет, т.к. heapq — мин-куча
            heappush(self._queue, PriorityItem(-priority, item, time()))
            self._counter += 1
            await incr("queue.priority.put")
            await gauge("queue.priority.size", len(self._queue))
            self._not_empty.notify()

    async def get(self) -> Any:
        """
        Извлекает элемент с наивысшим приоритетом.
        Если очередь пуста — ждет появления данных.
        """
        async with self._not_empty:
            while not self._queue:
                await self._not_empty.wait()

            item = heappop(self._queue)
            self._not_full.notify()
            await incr("queue.priority.get")
            await gauge("queue.priority.size", len(self._queue))
            return item.item

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
        Основной цикл воркера:
        - получает элемент с наивысшим приоритетом
        - выполняет (функцию, корутину и т.д.)
        - считает метрики
        """
        while self._running:
            try:
                item = await asyncio.wait_for(self.get(), timeout=1.0)

                async with Timer(f"queue.priority.worker.{worker_id}"):
                    if asyncio.iscoroutine(item):
                        await item
                    elif asyncio.iscoroutinefunction(item):
                        await item()
                    elif callable(item):
                        result = item()
                        if asyncio.iscoroutine(result):
                            await result

                await incr(f"queue.priority.worker.{worker_id}.processed")

            except asyncio.TimeoutError:
                continue
            except Exception:
                await incr(f"queue.priority.worker.{worker_id}.errors")
