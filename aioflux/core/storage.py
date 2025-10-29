"""
Реализации хранилищ данных.
Есть три варианта: в памяти, в Redis, и гибрид (память + Redis).
"""

import asyncio
from typing import Any, Dict, Optional

from redis.asyncio import Redis

from aioflux.core.base import now, Storage


class MemoryStorage(Storage):
    """
    Хранилище в памяти процесса.
    """

    def __init__(self, max_size: int = 100000):
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._max_size = max_size

    async def get(self, key: str) -> Optional[Any]:
        await self._cleanup_expired()
        return self._data.get(key)

    async def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        async with self._lock:
            # Если места нет - выкидываем самый старый
            if len(self._data) >= self._max_size and key not in self._data:
                oldest = min(self._expiry.items(), key=lambda x: x[1])[0] if self._expiry else None
                if oldest:
                    del self._data[oldest]
                    del self._expiry[oldest]

            self._data[key] = val
            if ttl:
                self._expiry[key] = now() + ttl

    async def incr(self, key: str, delta: float = 1) -> float:
        async with self._lock:
            val = self._data.get(key, 0) + delta
            self._data[key] = val
            return val

    async def decr(self, key: str, delta: float = 1) -> float:
        return await self.incr(key, -delta)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    async def exists(self, key: str) -> bool:
        await self._cleanup_expired()
        return key in self._data

    async def _cleanup_expired(self) -> None:
        current = now()
        expired = [k for k, exp in self._expiry.items() if exp <= current]
        for k in expired:
            await self.delete(k)


class RedisStorage(Storage):
    def __init__(self, url: str = "redis://localhost", pool_size: int = 10):
        self._url = url
        self._pool_size = pool_size
        self._redis = None

    async def _get_redis(self):
        if not self._redis:
            self._redis = await Redis.from_url(
                self._url,
                max_connections=self._pool_size,
                decode_responses=True
            )
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        r = await self._get_redis()
        val = await r.get(key)
        if val and val.replace('.', '', 1).replace('-', '', 1).isdigit():
            return float(val)
        return val

    async def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        r = await self._get_redis()
        if ttl:
            await r.setex(key, int(ttl), str(val))
        else:
            await r.set(key, str(val))

    async def incr(self, key: str, delta: float = 1) -> float:
        r = await self._get_redis()
        return await r.incrbyfloat(key, delta)

    async def decr(self, key: str, delta: float = 1) -> float:
        return await self.incr(key, -delta)

    async def delete(self, key: str) -> None:
        r = await self._get_redis()
        await r.delete(key)

    async def exists(self, key: str) -> bool:
        r = await self._get_redis()
        return await r.exists(key) > 0

    async def eval_script(self, script: str, keys: list, args: list) -> Any:
        """
        Выполняем Lua скрипт в Redis.
        Нужно для атомарных операций в rate limiter'ах.
        """
        r = await self._get_redis()
        return await r.eval(script, len(keys), *keys, *args)


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
