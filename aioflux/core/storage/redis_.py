from typing import Any, Optional

from redis.asyncio import Redis

from aioflux.core.storage.base import Storage


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
