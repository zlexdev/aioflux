import asyncio
from typing import Any, List

from aioflux.queues.base.base import BaseQueue
from aioflux.core.metrics import gauge, incr


class BroadcastQueue(BaseQueue):
    """
    Очередь вещания (Broadcast Queue).

    Все подписчики получают копию каждого элемента.
    Подходит для рассылки событий нескольким потребителям.
    """

    def __init__(self, max_size: int = 10000):
        """
        max_size — максимальный размер очереди для каждого подписчика.
        """
        self.max_size = max_size
        self._subscribers: List[asyncio.Queue] = []
        self._running = False
        self._lock = asyncio.Lock()

    async def put(self, item: Any, priority: int = 0) -> None:
        """
        Отправляет элемент всем подписчикам.

        Если у подписчика очередь переполнена — событие для него теряется.
        """
        async with self._lock:
            for queue in self._subscribers:
                try:
                    queue.put_nowait(item)
                except asyncio.QueueFull:
                    await incr("queue.broadcast.dropped")

            await incr("queue.broadcast.put")
            await gauge("queue.broadcast.subscribers", len(self._subscribers))

    async def get(self) -> Any:
        """
        Не используется — получение идёт через subscribe().
        """
        raise NotImplementedError("Use subscribe() instead")

    async def size(self) -> int:
        """Возвращает количество активных подписчиков."""
        async with self._lock:
            return len(self._subscribers)

    async def subscribe(self) -> asyncio.Queue:
        """
        Создаёт нового подписчика и возвращает его очередь.
        Каждый элемент, отправленный через put(), попадёт в эту очередь.
        """
        queue = asyncio.Queue(maxsize=self.max_size)
        async with self._lock:
            self._subscribers.append(queue)
            await incr("queue.broadcast.subscribed")
            await gauge("queue.broadcast.subscribers", len(self._subscribers))
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        """
        Отписывает подписчика и удаляет его очередь.
        """
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)
                await incr("queue.broadcast.unsubscribed")
                await gauge("queue.broadcast.subscribers", len(self._subscribers))

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        """
        Останавливает очередь.
        Очищает очереди всех подписчиков.
        """
        self._running = False
        async with self._lock:
            for queue in self._subscribers:
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
