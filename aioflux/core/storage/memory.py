import asyncio
from typing import Any, Dict, Optional

from aioflux.core.storage.base import Storage
from aioflux.utils.common import now


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
