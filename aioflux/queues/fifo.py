from aioflux.queues.base.base import BaseQueue
from aioflux.core.metrics import incr, gauge, Timer
from typing import Any, Optional, Callable, List
import asyncio


class FIFOQueue(BaseQueue):
    """
    Очередь FIFO (первым пришёл — первым ушёл).

    Поддерживает:
    - фиксированное количество воркеров
    - пакетную обработку (batch)
    - обработку функций, корутин и задач
    - метрики (размер, обработанные, ошибки)
    """

    def __init__(
        self,
        workers: int = 1,
        max_size: int = 10000,
        batch_size: int = 1,
        batch_timeout: float = 1.0,
        batch_fn: Optional[Callable[[List[Any]], Any]] = None
    ):
        """
        workers — количество параллельных воркеров
        max_size — максимальный размер очереди
        batch_size — сколько задач собираем в одну пачку
        batch_timeout — максимум ожидания, пока наберется batch
        batch_fn — функция обработки пачки (если задана, то выполняется вместо отдельных)
        """
        self.workers = workers
        self.max_size = max_size
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.batch_fn = batch_fn

        self._queue = asyncio.Queue(maxsize=max_size)
        self._tasks = []
        self._running = False

    async def put(self, item: Any, priority: int = 0) -> None:
        await self._queue.put(item)
        await incr("queue.fifo.put")
        await gauge("queue.fifo.size", self._queue.qsize())

    async def get(self) -> Any:
        item = await self._queue.get()
        await incr("queue.fifo.get")
        await gauge("queue.fifo.size", self._queue.qsize())
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
        - собирает batch задач
        - обрабатывает их (batch_fn или по отдельности)
        - считает метрики
        """
        while self._running:
            try:
                batch = await self._collect_batch()
                if not batch:
                    continue

                async with Timer(f"queue.fifo.worker.{worker_id}"):
                    if self.batch_fn:
                        if asyncio.iscoroutinefunction(self.batch_fn):
                            await self.batch_fn(batch)
                        else:
                            self.batch_fn(batch)
                    else:
                        for item in batch:
                            if asyncio.iscoroutine(item):
                                await item
                            elif asyncio.iscoroutinefunction(item):
                                await item()
                            elif callable(item):
                                result = item()
                                if asyncio.iscoroutine(result):
                                    await result

                await incr(f"queue.fifo.worker.{worker_id}.processed", len(batch))

            except Exception:
                await incr(f"queue.fifo.worker.{worker_id}.errors")

    async def _collect_batch(self) -> List[Any]:
        """
        Собирает batch задач.
        - ждет, пока не наберет batch_size или не истечет batch_timeout.
        - возвращает список задач для обработки.
        """
        batch = []
        deadline = asyncio.get_event_loop().time() + self.batch_timeout

        while len(batch) < self.batch_size:
            timeout = max(0, deadline - asyncio.get_event_loop().time())  # type: ignore
            if timeout <= 0 and batch:
                break

            try:
                item = await asyncio.wait_for(self.get(), timeout=timeout)
                batch.append(item)
            except asyncio.TimeoutError:
                break

        return batch
