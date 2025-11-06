from aioflux.limiters.base import BaseLimiter
from aioflux.core.metrics import incr
from typing import Dict, Any, List


class CompositeLimiter(BaseLimiter):
    """
    Комбинированный лимитер.

    Объединяет несколько лимитеров (token bucket, sliding window и т.п.)
    и пропускает запрос только если **все** лимитеры разрешили.

    Пример:
        composite = CompositeLimiter([
            TokenBucketLimiter(...),
            SlidingWindowLimiter(...)
        ])

        → запрос пройдет, только если оба лимитера внутри "ok".
    """

    def __init__(self, limiters: List[BaseLimiter]):
        """
        limiters — список объектов, реализующих интерфейс Limiter.
        """
        self.limiters = limiters

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Проверяет все лимитеры по очереди.
        Если хотя бы один отклонил — запрос блокируется.
        """
        for limiter in self.limiters:
            if not await limiter.acquire(key, tokens):
                await incr("limiter.composite.rejected")
                return False

        await incr("limiter.composite.accepted")
        return True

    async def release(self, key: str, tokens: float = 1) -> None:
        """
        Освобождает токены/счётчики во всех вложенных лимитерах.
        Обычно вызывается вручную, если нужно вернуть ресурсы.
        """
        for limiter in self.limiters:
            await limiter.release(key, tokens)

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """
        Возвращает сводную статистику по каждому вложенному лимитеру.
        """
        stats = {}
        for i, limiter in enumerate(self.limiters):
            stats[f"limiter_{i}"] = await limiter.get_stats(key)
        return stats
