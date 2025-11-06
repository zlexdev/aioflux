import asyncio
from dataclasses import dataclass, field
from time import time
from typing import Any, Awaitable, Callable, Dict, Generic, List, Optional, TypeVar

from aioflux import batch_gather, batch_process
from aioflux.core.metrics import gauge, incr
from aioflux.limiters.base import BaseLimiter
from aioflux.queues.base.typed_queue import Handler, TypedQueue
from aioflux.utils.batch import BatchCollector


T = TypeVar('T')
R = TypeVar('R', bound=Any)


@dataclass
class FluxConfig:
    """Конфиг для Flux процессора.

    workers: кол-во параллельных воркеров для обработки
    max_retries: сколько раз пытаться обработать при ошибке
    retry_delay: базовая задержка между попытками в секундах
    timeout: таймаут на обработку одного элемента
    key_fn: функция для генерации ключа из элемента (для лимитеров)
    """
    workers: int = 4
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: Optional[float] = None
    key_fn: Optional[Callable[[Any], str]] = field(default=lambda: lambda x: str(hash(x)))


class QueueFlux(Generic[T, R]):
    """Базовый процессор очереди с поддержкой rate limiting и ретраев.

    Запускает несколько воркеров, которые берут элементы из очереди и обрабатывают через handler.
    Поддерживает лимитер, таймауты, автоматические ретраи с экспоненциальной задержкой.
    Собирает статистику: processed, failed, rejected.
    """

    def __init__(
        self,
        queue: TypedQueue[T],
        handler: Handler[T, R],
        limiter: Optional[BaseLimiter] = None,
        config: Optional[FluxConfig] = None,
        name: str = "default"
    ):
        self.queue = queue
        self.handler = handler
        self.limiter = limiter
        self.config = config or FluxConfig()
        self.name = name
        self._tasks = []
        self._running = False
        self._stats = {"processed": 0, "failed": 0, "rejected": 0}

    async def submit(self, item: T, priority: int = 0) -> None:
        """
        Добавить элемент в очередь на обработку.

        item: данные для обработки
        priority: приоритет выполнения (выше = раньше)
        """
        await self.queue.put(item, priority)
        await incr(f"flux.{self.name}.submitted")

    async def start(self) -> None:
        """
        Запустить обработку очереди. Стартует воркеры
        """
        self._running = True
        await self.queue.start()
        self._tasks = [
            asyncio.create_task(self._worker(i))
            for i in range(self.config.workers)
        ]
        await incr(f"flux.{self.name}.started")

    async def stop(self) -> None:
        """
        Остановить обработку. Ждет завершения всех воркеров
        """
        self._running = False
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.queue.stop()
        await incr(f"flux.{self.name}.stopped")

    async def wait_complete(self, timeout: Optional[float] = None) -> bool:
        """
        Ожидать завершения обработки всех элементов в очереди.

        timeout: макс время ожидания в секундах (None = бесконечно)
        return: True если все обработано, False если таймаут
        """
        start = time()
        while True:
            size = await self.queue.size()
            if size == 0:
                await asyncio.sleep(0.1)
                if await self.queue.size() == 0:
                    return True

            if timeout and (time() - start) >= timeout:
                return False

            await asyncio.sleep(0.1)

    async def _worker(self, wid: int) -> None:
        """
        Воркер - берет элементы из очереди и передает в _process
        """
        while self._running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                await self._process(item, wid)
            except asyncio.TimeoutError:
                continue
            except Exception:
                await incr(f"flux.{self.name}.worker.{wid}.errors")

    async def _process(self, item: T, wid: int) -> Optional[R]:
        """
        Обработать один элемент с учетом лимитера, таймаута и ретраев.

        Алгоритм:
        1. Проверить лимитер - если не прошел, вернуть в очередь
        2. Попытаться обработать через handler с таймаутом
        3. При ошибке - ретрай с экспоненциальной задержкой
        4. Обновить статистику и метрики
        """
        key = self.config.key_fn(item) if self.config.key_fn else str(hash(item))

        if self.limiter:
            if not await self.limiter.acquire(key):
                self._stats["rejected"] += 1
                await incr(f"flux.{self.name}.rejected")
                await self.queue.put(item, 0)
                await asyncio.sleep(0.1)
                return None

        for attempt in range(self.config.max_retries):
            try:
                if self.config.timeout:
                    result = await asyncio.wait_for(
                        self.handler(item),
                        timeout=self.config.timeout
                    )
                else:
                    result = await self.handler(item)

                self._stats["processed"] += 1
                await incr(f"flux.{self.name}.processed")
                await gauge(f"flux.{self.name}.queue_size", await self.queue.size())
                return result

            except asyncio.TimeoutError:
                await incr(f"flux.{self.name}.timeout")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                continue

            except Exception:
                await incr(f"flux.{self.name}.errors")
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                self._stats["failed"] += 1
                break

        return None

    def stats(self) -> Dict[str, int]:
        """
        Получить копию статистики обработки
        """
        return self._stats.copy()


class BatchFlux(QueueFlux[T, R]):
    """Батч-процессор очереди. Накапливает элементы и обрабатывает пачками.

    Оптимизирует вызовы к БД/API через батчинг. Флашит батч по двум условиям:
    - набрался batch_size элементов
    - прошел batch_timeout с момента последнего флаша

    Использует BatchCollector для удобного накопления. Ограничивает параллелизм через семафор.
    """

    def __init__(
        self,
        queue: TypedQueue[T],
        handler: Callable[[list[T]], Awaitable[list[R]]],
        limiter: Optional[BaseLimiter] = None,
        config: Optional[FluxConfig] = None,
        name: str = "batch",
        batch_size: int = 100,
        batch_timeout: float = 1.0,
        max_concurrent: int = 10
    ):
        self._batch_handler = handler
        super().__init__(queue, self._batch_handler, limiter, config, name)
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_concurrent = max_concurrent
        self._sem = asyncio.Semaphore(max_concurrent)
        self._collector = None
        self._processing = 0
        self._processing_lock = asyncio.Lock()

    async def start(self) -> None:
        """
        Запустить батч-обработку. Создает BatchCollector и воркеры
        """
        self._running = True
        await self.queue.start()
        self._collector = BatchCollector(
            batch_size=self.batch_size,
            timeout=self.batch_timeout,
            callback=self._process_collected_batch
        )
        self._tasks = [
            asyncio.create_task(self._worker(i))
            for i in range(self.config.workers)
        ]
        await incr(f"flux.{self.name}.started")

    async def stop(self) -> None:
        """
        Остановить обработку. Флашит оставшиеся элементы перед выходом
        """
        self._running = False
        if self._collector:
            await self._collector.flush()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.queue.stop()
        await incr(f"flux.{self.name}.stopped")

    async def wait_complete(self, timeout: Optional[float] = None) -> bool:
        """
        Ожидать завершения обработки всех элементов с учетом батчинга.

        Ждёт пока: 1) очередь пуста, 2) нет активных batch операций.

        timeout: макс время ожидания в секундах (None = бесконечно)
        return: True если все обработано, False если таймаут
        """
        start = time()

        while True:
            size = await self.queue.size()
            async with self._processing_lock:
                processing = self._processing

            if size == 0 and processing == 0:
                await asyncio.sleep(self.batch_timeout + 0.2)

                if self._collector:
                    await self._collector.flush()

                await asyncio.sleep(0.5)

                async with self._processing_lock:
                    processing = self._processing

                if await self.queue.size() == 0 and processing == 0:
                    return True

            if timeout and (time() - start) >= timeout:
                if self._collector:
                    await self._collector.flush()
                return False

            await asyncio.sleep(0.1)

    async def batch_process(
        self,
        items: List[T],
        func: Callable[[List[T]], R | Awaitable[R]],
        batch_size: Optional[int] = None,
        max_concurrent: Optional[int] = None
    ) -> List[R]:
        return await batch_process(
            items,
            func,
            batch_size=batch_size or self.batch_size,
            max_concurrent=max_concurrent or self.max_concurrent
        )

    async def batch_gather(self, *funcs: Callable, batch_size: Optional[int] = None) -> List[Any]:
        return await batch_gather(*funcs, batch_size=batch_size or self.batch_size)

    async def _worker(self, wid: int) -> None:
        """
        Воркер для батч-обработки. Накапливает элементы и флашит по условиям
        """
        batch = []
        last_flush = time()

        while self._running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=0.1)

                if self._collector:
                    await self._collector.add(item)
                else:
                    batch.append(item)
                    if len(batch) >= self.batch_size or (time() - last_flush) >= self.batch_timeout:
                        await self._process_batch(batch, wid)
                        batch = []
                        last_flush = time()

            except asyncio.TimeoutError:
                if batch and (time() - last_flush) >= self.batch_timeout:
                    await self._process_batch(batch, wid)
                    batch = []
                    last_flush = time()
            except Exception:
                await incr(f"flux.{self.name}.worker.{wid}.errors")

    async def _process_batch(self, batch: list[T], wid: int) -> None:
        """
        Обработать один батч через handler с учетом лимитера
        """
        if not batch:
            return

        async with self._processing_lock:
            self._processing += 1

        try:
            async with self._sem:
                if self.limiter:
                    key = f"batch_{wid}"
                    if not await self.limiter.acquire(key, len(batch)):
                        await incr(f"flux.{self.name}.rejected")
                        for item in batch:
                            await self.queue.put(item, 0)
                        await asyncio.sleep(0.1)
                        return

                try:
                    await self._batch_handler(batch)
                    self._stats["processed"] += len(batch)
                    await incr(f"flux.{self.name}.processed", len(batch))
                except Exception:
                    self._stats["failed"] += len(batch)
                    await incr(f"flux.{self.name}.errors")
        finally:
            async with self._processing_lock:
                self._processing -= 1

    async def _process_collected_batch(self, items: List[T]) -> None:
        """
        Callback для BatchCollector. Обрабатывает накопленный батч
        """
        if not items:
            return

        async with self._processing_lock:
            self._processing += 1

        try:
            async with self._sem:
                if self.limiter:
                    key = f"collected_{time()}"
                    if not await self.limiter.acquire(key, len(items)):
                        self._stats["rejected"] += len(items)
                        await incr(f"flux.{self.name}.rejected")
                        for item in items:
                            await self.queue.put(item, 0)
                        await asyncio.sleep(0.1)
                        return

                try:
                    await self._batch_handler(items)
                    self._stats["processed"] += len(items)
                    await incr(f"flux.{self.name}.processed", len(items))
                except Exception:
                    self._stats["failed"] += len(items)
                    await incr(f"flux.{self.name}.errors")
        finally:
            async with self._processing_lock:
                self._processing -= 1


class PriorityFlux(QueueFlux[T, R]):
    """Процессор с поддержкой приоритетов и индивидуальных лимитеров на приоритет.

    Позволяет задавать разные rate limits для разных приоритетов.
    Например: вип юзеры (priority=10) - 1000 rpm, обычные (priority=0) - 100 rpm.
    """

    def __init__(
        self,
        queue: TypedQueue[T],
        handler: Handler[T, R],
        limiters: Dict[int, BaseLimiter],
        config: Optional[FluxConfig] = None,
        name: str = "priority"
    ):
        super().__init__(queue, handler, None, config, name)
        self.limiters = limiters

    async def submit(self, item: T, priority: int = 0) -> None:
        """

        Добавить элемент с приоритетом
        """
        await self.queue.put(item, priority)

    async def _process(self, item: T, wid: int) -> Optional[R]:
        """
        Обработать элемент с учетом его приоритета и соответствующего лимитера
        """
        priority = getattr(item, 'priority', 0)
        limiter = self.limiters.get(priority)

        if limiter:
            key = self.config.key_fn(item) if self.config.key_fn else str(hash(item))
            if not await limiter.acquire(key):
                await self.queue.put(item, priority)
                await asyncio.sleep(0.1)
                return None

        try:
            result = await self.handler(item)
            self._stats["processed"] += 1
            await incr(f"flux.{self.name}.p{priority}.processed")
            return result
        except Exception:
            self._stats["failed"] += 1
            await incr(f"flux.{self.name}.errors")
            return None
