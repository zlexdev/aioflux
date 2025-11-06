from typing import Any, Optional

from aioflux.core.storage.base import Storage
from aioflux.core.storage.memory import MemoryStorage
from aioflux.core.storage.redis_ import RedisStorage


class HybridStorage(Storage):
    """
    Двухуровневое хранилище: L1 (память) + L2 (Redis).

    Горячие данные хранятся в памяти для скорости,
    холодные - в Redis для персистентности.
    Классический read-aside + write-through кэш.
    """

    def __init__(self, redis_url: str = "redis://localhost", l1_size: int = 10000):
        self._l1 = MemoryStorage(max_size=l1_size)  # Быстрый кэш
        self._l2 = RedisStorage(redis_url)  # Постоянное хранилище

    async def get(self, key: str) -> Optional[Any]:
        """
        Сначала смотрим в L1 (память).
        Если нет - идем в L2 (Redis) и кэшируем в L1.
        """
        val = await self._l1.get(key)
        if val is None:
            val = await self._l2.get(key)
            if val is not None:
                # Кэшируем на минуту
                await self._l1.set(key, val, ttl=60)
        return val

    async def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        """
        Пишем в оба слоя сразу (write-through).
        В L1 храним не дольше минуты.
        """
        await self._l1.set(key, val, ttl=min(ttl, 60) if ttl else 60)
        await self._l2.set(key, val, ttl=ttl)

    async def incr(self, key: str, delta: float = 1) -> float:
        """
        Инкремент идет только в L2 (Redis).
        L1 инвалидируем чтобы не было рассинхрона.
        """
        await self._l1.delete(key)
        return await self._l2.incr(key, delta)

    async def decr(self, key: str, delta: float = 1) -> float:
        """Декремент - аналогично инкременту"""
        return await self.incr(key, -delta)

    async def delete(self, key: str) -> None:
        """Удаляем из обоих слоев"""
        await self._l1.delete(key)
        await self._l2.delete(key)

    async def exists(self, key: str) -> bool:
        """Проверяем оба слоя"""
        return await self._l1.exists(key) or await self._l2.exists(key)
