from typing import List, Callable, Any, TypeVar, Optional
import asyncio


T = TypeVar('T')
R = TypeVar('R')


async def batch_process(
    items: List[T],
    func: Callable[[List[T]], R],
    batch_size: int = 100,
    max_concurrent: int = 10
) -> List[R]:
    """
    Параллельная обработка элементов списком (batch'ами).

    Разбивает список `items` на части по `batch_size`,
    запускает обработку с ограничением параллелизма `max_concurrent`.

    Пример:
        results = await batch_process(urls, fetch_urls, batch_size=50, max_concurrent=5)
    """
    batches = [
        items[i:i + batch_size]
        for i in range(0, len(items), batch_size)
    ]

    sem = asyncio.Semaphore(max_concurrent)

    async def process_batch(batch: List[T]) -> R:
        async with sem:
            if asyncio.iscoroutinefunction(func):
                return await func(batch)
            return func(batch)

    tasks = [process_batch(batch) for batch in batches]
    return await asyncio.gather(*tasks)


async def batch_gather(
    *funcs: Callable,
    batch_size: int = 10
) -> List[Any]:
    """
    Выполняет набор функций (или корутин) пачками.

    Используется, если нужно собрать много асинхронных вызовов,
    но не выполнять их все сразу (ограничить нагрузку).

    Пример:
        results = await batch_gather(*tasks, batch_size=20)
    """
    results = []

    for i in range(0, len(funcs), batch_size):
        batch = funcs[i:i + batch_size]
        batch_results = await asyncio.gather(*[
            f() if asyncio.iscoroutinefunction(f) else asyncio.to_thread(f)
            for f in batch
        ])
        results.extend(batch_results)

    return results


class BatchCollector:
    """
    Асинхронный сборщик событий в пачки (batch collector).

    Накапливает элементы в буфере, пока:
    - не наберется `batch_size`, или
    - не пройдет `timeout` секунд.

    После этого вызывает callback с собранной пачкой.
    """

    def __init__(
        self,
        batch_size: int = 100,
        timeout: float = 1.0,
        callback: Optional[Callable[[List[Any]], Any]] = None
    ):
        """
        batch_size — размер одной пачки
        timeout — максимальная задержка перед отправкой
        callback — функция обработки пачки
        """
        self.batch_size = batch_size
        self.timeout = timeout
        self.callback = callback

        self._items: List[Any] = []
        self._lock = asyncio.Lock()
        self._last_flush = asyncio.get_event_loop().time()
        self._flush_task: Optional[asyncio.Task] = None

    async def add(self, item: Any) -> None:
        """
        Добавляет элемент в буфер.
        При достижении лимита — вызывает flush.
        """
        async with self._lock:
            self._items.append(item)

            if len(self._items) >= self.batch_size:
                await self._flush()
            elif not self._flush_task:
                self._flush_task = asyncio.create_task(self._auto_flush())

    async def _flush(self) -> None:
        """Выгружает накопленные элементы и вызывает callback."""
        if not self._items:
            return

        items = self._items[:]
        self._items.clear()
        self._last_flush = asyncio.get_event_loop().time()

        if self.callback:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(items)
            else:
                self.callback(items)

    async def _auto_flush(self) -> None:
        """
        Следит за таймаутом и автоматически вызывает flush.
        Если в течение timeout не было активности — сбрасывает пачку.
        """
        while True:
            await asyncio.sleep(self.timeout)
            async with self._lock:
                if asyncio.get_event_loop().time() - self._last_flush >= self.timeout:
                    await self._flush()
                    self._flush_task = None
                    break

    async def flush(self) -> None:
        """
        Принудительно сбрасывает буфер.
        """
        async with self._lock:
            await self._flush()
