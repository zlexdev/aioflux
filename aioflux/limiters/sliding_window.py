import asyncio
from bisect import bisect_left, insort
from typing import Any, Dict, List, Optional

from aioflux.utils.common import now
from aioflux.core.storage.base import Storage
from aioflux.limiters.base import BaseLimiter
from aioflux.core.metrics import incr
from aioflux.core.storage.memory import MemoryStorage
from aioflux.core.storage.redis_ import RedisStorage


class SlidingWindowLimiter(BaseLimiter):
    """
    Лимитер на основе скользящего окна (sliding window).

    Контролирует количество событий за заданный интервал времени.
    В отличие от токен-бакета, хранит реальные отметки времени событий
    и позволяет более точно считать лимит.

    Пример:
        rate=5, per=1.0 → максимум 5 событий за последнюю секунду.
    """

    def __init__(
        self,
        rate: float,
        per: float = 1.0,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        rate — максимально допустимое число событий за интервал
        per — длительность окна (в секундах)
        storage — хранилище (по умолчанию память)
        scope — имя набора лимитов (для метрик)
        """
        self.rate = rate
        self.per = per
        self.storage = storage or MemoryStorage()
        self.scope = scope
        self._windows: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Проверяет, можно ли разрешить событие для данного ключа.
        Удаляет старые записи, добавляет текущую, если лимит не превышен.
        """
        full_key = f"{self.scope}:{key}"
        current = now()
        cutoff = current - self.per

        async with self._lock:
            if full_key not in self._windows:
                self._windows[full_key] = []

            window = self._windows[full_key]

            # очищаем старые значения (до cutoff)
            idx = bisect_left(window, cutoff)
            self._windows[full_key] = window[idx:]

            # если ещё можно — добавляем текущее событие
            if len(self._windows[full_key]) < self.rate:
                insort(self._windows[full_key], current)
                await incr(f"limiter.{self.scope}.accepted")
                return True

            await incr(f"limiter.{self.scope}.rejected")
            return False

    async def release(self, key: str, tokens: float = 1) -> None:
        """Не используется (ограничение по времени, не по возврату токенов)."""
        pass

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """
        Возвращает текущее состояние окна:
        сколько событий сейчас в пределах периода, сколько осталось до лимита.
        """
        full_key = f"{self.scope}:{key}"
        async with self._lock:
            window = self._windows.get(full_key, [])
            current = now()
            cutoff = current - self.per
            valid = [t for t in window if t >= cutoff]

            return {
                "current_count": len(valid),
                "max_count": self.rate,
                "window_seconds": self.per,
                "available": self.rate - len(valid)
            }


class RedisSlidingWindow(BaseLimiter):
    """
    Реализация скользящего окна с использованием Redis (через ZSET).

    Redis хранит временные метки событий с сортировкой по времени.
    Старые события удаляются, и проверяется количество за окно.
    """

    def __init__(
        self,
        rate: float,
        per: float = 1.0,
        storage: Optional[RedisStorage] = None,
        scope: str = "default"
    ):
        """
        rate — максимум событий за окно
        per — длительность окна в секундах
        storage — RedisStorage с поддержкой eval_script
        scope — префикс для ключей и метрик
        """
        self.rate = rate
        self.per = per
        self.storage = storage
        self.scope = scope

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Основная логика лимита:
        - Удаляем старые записи из ZSET (вышедшие за пределы окна)
        - Проверяем текущее количество
        - Если меньше лимита — добавляем новое событие
        """
        if not self.storage:
            return False

        full_key = f"{self.scope}:{key}"
        current = now()
        cutoff = current - self.per

        script = """
        local key = KEYS[1]
        local cutoff = tonumber(ARGV[1])
        local current = tonumber(ARGV[2])
        local rate = tonumber(ARGV[3])

        redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
        local count = redis.call('ZCARD', key)

        if count < rate then
            redis.call('ZADD', key, current, current)
            redis.call('EXPIRE', key, 3600)
            return 1
        end
        return 0
        """

        result = await self.storage.eval_script(
            script,
            [full_key],
            [cutoff, current, self.rate]
        )

        if result == 1:
            await incr(f"limiter.{self.scope}.accepted")
            return True

        await incr(f"limiter.{self.scope}.rejected")
        return False

    async def release(self, key: str, tokens: float = 1) -> None:
        pass

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """
        Возвращает базовую информацию о лимите.
        (точный счётчик можно получить отдельным ZCARD-запросом).
        """
        # full_key = f"{self.scope}:{key}"
        return {
            "max_count": self.rate,
            "window_seconds": self.per
        }
