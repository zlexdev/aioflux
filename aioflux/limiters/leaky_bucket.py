import asyncio
from typing import Any, Dict, Optional

from aioflux.utils.common import now
from aioflux.core.storage.base import Storage
from aioflux.limiters.base import BaseLimiter
from aioflux.core.metrics import gauge, incr
from aioflux.core.storage.memory import MemoryStorage


class LeakyBucketLimiter(BaseLimiter):
    """
    Лимитер по принципу "протекающего ведра" (Leaky Bucket).

    Работает как очередь с ограниченной скоростью "утечки":
    - уровень ведра растет при каждом запросе (добавляем токены)
    - со временем уровень падает (токены вытекают с постоянной скоростью)
    - если ведро переполнено — запрос отклоняется

    Применяется для стабилизации нагрузки: выравнивает поток запросов.
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        rate — скорость утечки (токенов в секунду)
        capacity — максимальный объем ведра (лимит накопления)
        storage — хранилище состояния (Redis, память)
        scope — имя набора лимитов (для метрик)
        """
        self.rate = rate
        self.capacity = capacity
        self.storage = storage or MemoryStorage()
        self.scope = scope
        self._locks = {}

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Пытается добавить `tokens` в ведро.
        - Если после утечки хватает места — добавляем и разрешаем.
        - Если переполнено — отклоняем.
        """
        full_key = f"{self.scope}:{key}"
        lock = self._get_lock(full_key)

        async with lock:
            current = now()

            last_time = await self.storage.get(f"{full_key}:time")
            level = await self.storage.get(f"{full_key}:level")

            if last_time is None:
                last_time = current
                level = 0

            # считаем, сколько "вытекло" с прошлого раза
            elapsed = current - last_time
            leaked = elapsed * self.rate
            new_level = max(0, level - leaked)

            if new_level + tokens <= self.capacity:
                # добавляем токены — запрос разрешен
                new_level += tokens
                await self.storage.set(f"{full_key}:level", new_level)
                await self.storage.set(f"{full_key}:time", current)
                await incr(f"limiter.{self.scope}.accepted")
                await gauge(f"limiter.{self.scope}.level", new_level)
                return True

            # не хватило места — отклоняем
            await self.storage.set(f"{full_key}:level", new_level)
            await self.storage.set(f"{full_key}:time", current)
            await incr(f"limiter.{self.scope}.rejected")
            return False

    async def release(self, key: str, tokens: float = 1) -> None:
        """
        Принудительно "выпускает" часть токенов (уменьшает уровень).
        Используется редко — в основном для ручного сброса нагрузки.
        """
        full_key = f"{self.scope}:{key}"
        lock = self._get_lock(full_key)

        async with lock:
            level = await self.storage.get(f"{full_key}:level") or 0
            new_level = max(0, level - tokens)
            await self.storage.set(f"{full_key}:level", new_level)

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """
        Возвращает состояние ведра:
        - текущий уровень
        - общая ёмкость
        - скорость утечки
        """
        full_key = f"{self.scope}:{key}"
        level = await self.storage.get(f"{full_key}:level") or 0
        last_time = await self.storage.get(f"{full_key}:time") or now()

        return {
            "current_level": level,
            "capacity": self.capacity,
            "leak_rate": self.rate,
            "last_update": last_time
        }
