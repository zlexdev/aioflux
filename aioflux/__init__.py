"""
aioflux - высокопроизводительная библиотека для управления рейт-лимитинга и управления очередями.

Основные возможности:
- рейт-лимитинг с разными алгоритмами (token bucket, sliding window и т.д.)
- Приоритетные очереди и батчинг
- Декораторы
- Поддержка Redis
- Сбор метрик и мониторинг

Простой пример:
    from aioflux import RateLimiter, rate_limit
    
    # Создаем лимитер на 100 запросов в минуту
    limiter = RateLimiter.token_bucket(rate=100, per=60)
    
    # Или используем декоратор
    @rate_limit(rate=100, per=60)
    async def api_call():
        pass
"""

from aioflux.core.base import Limiter, QueueBase, Storage
from aioflux.core.metrics import gauge, get_stats, incr, Timer, timing
from aioflux.core.storage import HybridStorage, MemoryStorage, RedisStorage
from aioflux.decorators.circuit_breaker import circuit_breaker, CircuitBreakerOpen
from aioflux.decorators.queue import queued, queued_sync
from aioflux.decorators.rate_limit import rate_limit, rate_limit_sync
from aioflux.limiters.adaptive import AdaptiveLimiter
from aioflux.limiters.composite import CompositeLimiter
from aioflux.limiters.leaky_bucket import LeakyBucketLimiter
from aioflux.limiters.sliding_window import RedisSlidingWindow, SlidingWindowLimiter
from aioflux.limiters.token_bucket import FastTokenBucket, TokenBucketLimiter
from aioflux.managers.coordinator import Coordinator
from aioflux.managers.pool import WorkerPool
from aioflux.managers.scheduler import Scheduler
from aioflux.queues.broadcast import BroadcastQueue
from aioflux.queues.dedupe import DedupeQueue
from aioflux.queues.delay import DelayQueue
from aioflux.queues.fifo import FIFOQueue
from aioflux.queues.priority import PriorityQueue
from aioflux.utils.backoff import backoff, backoff_decorator
from aioflux.utils.batch import batch_gather, batch_process, BatchCollector
from aioflux.utils.monitoring import ConsoleMonitor, Monitor, PrometheusExporter


__version__ = "0.1.0"

__all__ = (
    "Limiter",
    "QueueBase",
    "Storage",
    "MemoryStorage",
    "RedisStorage",
    "HybridStorage",
    "get_stats",
    "incr",
    "gauge",
    "timing",
    "Timer",
    "TokenBucketLimiter",
    "FastTokenBucket",
    "SlidingWindowLimiter",
    "RedisSlidingWindow",
    "LeakyBucketLimiter",
    "AdaptiveLimiter",
    "CompositeLimiter",
    "PriorityQueue",
    "FIFOQueue",
    "DelayQueue",
    "DedupeQueue",
    "BroadcastQueue",
    "rate_limit",
    "rate_limit_sync",
    "queued",
    "queued_sync",
    "circuit_breaker",
    "CircuitBreakerOpen",
    "WorkerPool",
    "Scheduler",
    "Coordinator",
    "backoff",
    "backoff_decorator",
    "batch_process",
    "batch_gather",
    "BatchCollector",
    "Monitor",
    "ConsoleMonitor",
    "PrometheusExporter",
    "RateLimiter",
    "Queue",
)


class RateLimiter:
    """
    Фабрика для создания rate limiter'ов.
    Удобнее чем импортировать каждый класс отдельно.
    """

    @staticmethod
    def token_bucket(rate: float, per: float = 1.0, burst: float = None, **kwargs):
        """
        Token Bucket - самый быстрый алгоритм.
        
        Параметры:
            rate: сколько токенов даем в период
            per: период в секундах (по умолчанию 1 секунда)
            burst: максимум токенов в корзине (по умолчанию = rate)
        
        Пример:
            # 100 запросов в минуту с burst до 150
            limiter = RateLimiter.token_bucket(rate=100, per=60, burst=150)
        """
        return TokenBucketLimiter(rate, per, burst, **kwargs)

    @staticmethod
    def sliding_window(rate: float, per: float = 1.0, **kwargs):
        """
        Sliding Window - самый точный алгоритм.
        
        Не дает делать burst'ы, строго контролирует rate в скользящем окне.
        """
        return SlidingWindowLimiter(rate, per, **kwargs)

    @staticmethod
    def leaky_bucket(rate: float, capacity: float, **kwargs):
        """
        Leaky Bucket - сглаживает нагрузку.
        
        Хорош когда надо равномерно распределить запросы во времени.
        """
        return LeakyBucketLimiter(rate, capacity, **kwargs)

    @staticmethod
    def adaptive(initial_rate: float = 100, **kwargs):
        """
        Adaptive - самонастраивающийся лимитер.
        
        Использует AIMD алгоритм: при ошибках уменьшает rate,
        при успехе - увеличивает. Сам подстраивается под нагрузку.
        """
        return AdaptiveLimiter(initial_rate, **kwargs)

    @staticmethod
    def composite(*limiters):
        """
        Составной лимитер - комбинирует несколько.
        
        Полезно когда нужно ограничить и по минутам и по часам:
            RateLimiter.composite(
                RateLimiter.token_bucket(100, per=60),  # 100/мин
                RateLimiter.token_bucket(1000, per=3600)  # 1000/час
            )
        """
        return CompositeLimiter(list(limiters))


class Queue:
    """
    Фабрика для создания очередей.
    Разные очереди под разные задачи.
    """

    @staticmethod
    def priority(workers: int = 1, **kwargs):
        """
        Приоритетная очередь.
        Задачи с высоким priority выполняются первыми.
        """
        return PriorityQueue(workers=workers, **kwargs)

    @staticmethod
    def fifo(workers: int = 1, **kwargs):
        """
        FIFO очередь с батчингом.
        Может накапливать задачи и обрабатывать пачками - экономит на DB/API вызовах.
        """
        return FIFOQueue(workers=workers, **kwargs)

    @staticmethod
    def delay(workers: int = 1, **kwargs):
        """
        Очередь с отложенным выполнением.
        Можно запланировать задачу на потом.
        """
        return DelayQueue(workers=workers, **kwargs)

    @staticmethod
    def dedupe(workers: int = 1, **kwargs):
        """
        Очередь с дедупликацией.
        Автоматом отсеивает одинаковые задачи.
        """
        return DedupeQueue(workers=workers, **kwargs)

    @staticmethod
    def broadcast(**kwargs):
        """
        Broadcast очередь (pub/sub).
        Одна задача уходит всем подписчикам.
        """
        return BroadcastQueue(**kwargs)
