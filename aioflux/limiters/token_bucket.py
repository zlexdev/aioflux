import asyncio
from typing import Any, Dict, Optional

from aioflux.utils.common import now
from aioflux.core.storage.base import Storage
from aioflux.limiters.base import BaseLimiter
from aioflux.core.metrics import gauge, incr
from aioflux.core.storage.memory import MemoryStorage


class TokenBucketLimiter(BaseLimiter):
    """
    Классический токен-бакет с хранением состояния в Storage (например Redis).

    Управляет скоростью выполнения запросов:
    - в бакете хранится ограниченное число "токенов"
    - каждый запрос забирает N токенов
    - токены восстанавливаются со временем с заданной скоростью

    Пример:
        rate=5, per=1 → 5 токенов в секунду
        burst=10 → можно сделать 10 запросов подряд без ожидания

    Метрики:
    - limiter.<scope>.accepted — разрешенные запросы
    - limiter.<scope>.rejected — отклоненные запросы
    - limiter.<scope>.tokens — текущее количество токенов
    """

    def __init__(
        self,
        rate: float,
        per: float = 1.0,
        burst: Optional[float] = None,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        rate — сколько токенов добавляем за интервал `per`
        per — длительность интервала (в секундах)
        burst — максимальное число токенов в бакете
        storage — хранилище для токенов (Redis, память и т.д.)
        scope — имя набора лимитов (для метрик)
        """
        self.rate = rate
        self.per = per
        self.burst = burst or rate
        self.storage = storage or MemoryStorage()
        self.scope = scope
        self._refill_rate = rate / per
        self._locks = {}

    def _get_lock(self, key: str) -> asyncio.Lock:
        """Возвращает лок на ключ (создает при первом обращении)"""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Запрашиваем `tokens` токенов.
        Если хватает — уменьшаем счетчик и пропускаем.
        Если нет — отклоняем.
        """
        full_key = f"{self.scope}:{key}"
        lock = self._get_lock(full_key)

        async with lock:
            current_time = now()

            last_time = await self.storage.get(f"{full_key}:time")
            last_tokens = await self.storage.get(f"{full_key}:tokens")

            if last_time is None:
                last_time = current_time
                last_tokens = self.burst

            elapsed = current_time - last_time
            new_tokens = min(self.burst, last_tokens + elapsed * self._refill_rate)

            if new_tokens >= tokens:
                new_tokens -= tokens
                await self.storage.set(f"{full_key}:tokens", new_tokens)
                await self.storage.set(f"{full_key}:time", current_time)
                await incr(f"limiter.{self.scope}.accepted")
                await gauge(f"limiter.{self.scope}.tokens", new_tokens)
                return True

            await self.storage.set(f"{full_key}:tokens", new_tokens)
            await self.storage.set(f"{full_key}:time", current_time)
            await incr(f"limiter.{self.scope}.rejected")
            return False

    async def release(self, key: str, tokens: float = 1) -> None:
        """Возврат токенов обратно в бакет."""
        k = f"{self.scope}:{key}"
        lock = self._get_lock(k)
        async with lock:
            t = now()
            last_t = await self.storage.get(f"{k}:time") or t
            cur = await self.storage.get(f"{k}:tokens") or self.burst
            elapsed = t - last_t
            new = min(self.burst, cur + elapsed * self._refill_rate + tokens)
            await self.storage.set(f"{k}:tokens", new)
            await self.storage.set(f"{k}:time", t)
            await gauge(f"limiter.{self.scope}.tokens", new)

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """Возвращает состояние ведра."""
        k = f"{self.scope}:{key}"
        t = now()
        last_t = await self.storage.get(f"{k}:time") or t
        cur = await self.storage.get(f"{k}:tokens") or self.burst
        avail = min(self.burst, cur + (t - last_t) * self._refill_rate)
        return {
            "available_tokens": avail,
            "max_tokens": self.burst,
            "refill_rate": self._refill_rate,
            "last_update": last_t,
        }


class FastTokenBucket(BaseLimiter):
    """
    Упрощённый и очень быстрый вариант токен-бакета.

    Используется для локального ограничения частоты вызовов
    без внешнего хранилища (всё в памяти, без await в storage).

    Особенности:
    - высокая производительность (всё синхронно в памяти)
    - подходит для высоконагруженных потоков
    - не гарантирует глобальную консистентность между процессами
    """

    def __init__(self, rate: float, per: float = 1.0, burst: Optional[float] = None):
        """
        rate — количество токенов, добавляемых за период `per`
        per — интервал (в секундах)
        burst — максимальное количество токенов (если None, то = rate)
        """
        self.rate = rate
        self.per = per
        self.burst = burst or rate
        self._refill_rate = rate / per
        self._buckets: Dict[str, Dict[str, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Проверяет, можно ли взять `tokens` токенов.
        Возвращает True — разрешено, False — превышен лимит.
        """
        async with self._lock:
            current = now()

            bucket = self._buckets.setdefault(key, {"tokens": self.burst, "time": current})

            elapsed = current - bucket["time"]
            bucket["tokens"] = min(self.burst, bucket["tokens"] + elapsed * self._refill_rate)
            bucket["time"] = current

            if bucket["tokens"] >= tokens:
                bucket["tokens"] -= tokens
                await incr("limiter.fast.accepted")
                return True

            await incr("limiter.fast.rejected")
            return False

    async def release(self, key: str, tokens: float = 1) -> None:
        """Возвращает токены обратно (например, при отмене операции)."""
        async with self._lock:
            if key in self._buckets:
                bucket = self._buckets[key]
                bucket["tokens"] = min(self.burst, bucket["tokens"] + tokens)

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """Возвращает текущее состояние ведра."""
        async with self._lock:
            bucket = self._buckets.get(key, {"tokens": self.burst, "time": now()})
            return {
                "available_tokens": bucket["tokens"],
                "max_tokens": self.burst,
                "refill_rate": self._refill_rate
            }
