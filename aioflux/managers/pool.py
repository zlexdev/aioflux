import asyncio
from typing import Any, Callable, List, Optional

from aioflux.core.metrics import gauge, incr


class WorkerPool:
    """
    Асинхронный пул воркеров.

    Задачи отправляются в очередь, воркеры их разбирают.
    Количество воркеров регулируется автоматически:
    - увеличивается при росте нагрузки
    - уменьшается при простое
    """

    def __init__(
        self,
        min_workers: int = 1,
        max_workers: int = 10,
        scale_up_threshold: float = 0.8,
        scale_down_threshold: float = 0.2,
        check_interval: float = 5.0
    ):
        """
        min_workers — минимальное число воркеров (держим всегда)
        max_workers — максимум, больше не создаем
        scale_up_threshold — при какой загрузке добавляем воркера
        scale_down_threshold — при какой уменьшаем
        check_interval — как часто проверяем нагрузку
        """
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self.check_interval = check_interval

        self._queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._running = True
        for _ in range(self.min_workers):
            await self._add_worker()
        self._monitor_task = asyncio.create_task(self._monitor())

    async def stop(self) -> None:
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def submit(self, func: Callable, *args, **kwargs) -> Any:
        """
        Добавление задачи в очередь.
        func — любая функция (синхронная или асинхронная).
        Возвращает результат выполнения.
        """
        future = asyncio.Future()
        await self._queue.put((func, args, kwargs, future))
        await incr("pool.submit")
        return await future

    async def _add_worker(self) -> None:
        worker = asyncio.create_task(self._worker())
        self._workers.append(worker)
        await gauge("pool.workers", len(self._workers))

    async def _remove_worker(self) -> None:
        if self._workers:
            worker = self._workers.pop()
            worker.cancel()
            await gauge("pool.workers", len(self._workers))

    async def _worker(self) -> None:
        """
        Воркеры извлекают задачи из очереди и выполняют их.
        При ошибках ставим исключение в future, чтобы вызывающий узнал
        """
        while self._running:
            try:
                func, args, kwargs, future = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )

                try:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)
                    future.set_result(result)
                    await incr("pool.processed")
                except Exception as e:
                    future.set_exception(e)
                    await incr("pool.errors")
            except asyncio.TimeoutError:
                continue

    async def _monitor(self) -> None:
        """
        Мониторинг пула.
        Каждые `check_interval` секунд проверяет загрузку
        и решает — добавить или убрать воркеров
        """
        while self._running:
            await asyncio.sleep(self.check_interval)

            queue_size = self._queue.qsize()
            worker_count = len(self._workers)
            if worker_count == 0:
                continue

            load = queue_size / worker_count

            if load > self.scale_up_threshold and worker_count < self.max_workers:
                await self._add_worker()
                await incr("pool.scaled_up")

            elif load < self.scale_down_threshold and worker_count > self.min_workers:
                await self._remove_worker()
                await incr("pool.scaled_down")
