"""
aioflux - высокопроизводительная библиотека для управления рейт-лимитинга и управления очередями.

Основные возможности:
- рейт-лимитинг с разными алгоритмами (token bucket, sliding window и т.д.)
- Приоритетные очереди и батчинг
- Декораторы
- Поддержка Redis
- Сбор метрик и мониторинг

Простой пример:
    from aioflux import LimiterFactory, rate_limit
    
    # Создаем лимитер на 100 запросов в минуту
    limiter = LimiterFactory.token_bucket(rate=100, per=60)
    
    # Или используем декоратор
    @rate_limit(rate=100, per=60)
    async def api_call():
        pass
"""

from typing import Any, Callable, List, Optional

from aioflux.core.metrics import gauge, get_stats, incr, Timer, timing
from aioflux.core.storage.base import Storage
from aioflux.core.storage.hybrid import HybridStorage
from aioflux.core.storage.memory import MemoryStorage
from aioflux.core.storage.redis_ import RedisStorage
from aioflux.decorators.circuit_breaker import circuit_breaker, CircuitBreakerOpen
from aioflux.decorators.queue import queued, queued_sync
from aioflux.decorators.rate_limit import rate_limit, rate_limit_sync
from aioflux.flux import BatchFlux, FluxConfig, PriorityFlux, QueueFlux
from aioflux.limiters.adaptive import AdaptiveLimiter
from aioflux.limiters.base import BaseLimiter
from aioflux.limiters.composite import CompositeLimiter
from aioflux.limiters.leaky_bucket import LeakyBucketLimiter
from aioflux.limiters.sliding_window import RedisSlidingWindow, SlidingWindowLimiter
from aioflux.limiters.token_bucket import FastTokenBucket, TokenBucketLimiter
from aioflux.managers.coordinator import Coordinator
from aioflux.managers.pool import WorkerPool
from aioflux.managers.scheduler import Scheduler
from aioflux.queues.base.base import BaseQueue
from aioflux.queues.broadcast import BroadcastQueue
from aioflux.queues.dedupe import DedupeQueue
from aioflux.queues.delay import DelayQueue
from aioflux.queues.fifo import FIFOQueue
from aioflux.queues.priority import PriorityQueue
from aioflux.utils.backoff import backoff, backoff_decorator
from aioflux.utils.batch import batch_gather, batch_process, BatchCollector
from aioflux.utils.monitoring import ConsoleMonitor, Monitor, PrometheusExporter


__version__ = "0.1.3"

__all__ = (
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
    "LimiterFactory",
    "QueueFactory",
    "FluxConfig",
    'PriorityFlux',
    'QueueFlux',
    'BatchFlux'
)


class LimiterFactory:
    """
    Фабрика для создания rate limiter'ов.
    Удобнее чем импортировать каждый класс отдельно.
    """

    @staticmethod
    def token_bucket(
        rate: float,
        per: float = 1.0,
        burst: Optional[float] = None,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        Token Bucket - самый быстрый алгоритм.

        Параметры:
            rate: сколько токенов даем в период
            per: период в секундах (по умолчанию 1 секунда)
            burst: максимум токенов в корзине (по умолчанию = rate)
            storage: хранилище для токенов (Redis, память и т.д.)
            scope: имя набора лимитов (для метрик)

        Пример:
            # 100 запросов в минуту с burst до 150
            limiter = LimiterFactory.token_bucket(rate=100, per=60, burst=150)
        """
        return TokenBucketLimiter(rate, per, burst, storage, scope)

    @staticmethod
    def fast_token_bucket(
        rate: float,
        per: float = 1.0,
        burst: Optional[float] = None
    ):
        """
        Упрощённый и очень быстрый вариант токен-бакета.

        Параметры:
            rate: количество токенов, добавляемых за период `per`
            per: интервал (в секундах)
            burst: максимальное количество токенов (если None, то = rate)
        """
        return FastTokenBucket(rate, per, burst)

    @staticmethod
    def sliding_window(
        rate: float,
        per: float = 1.0,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        Sliding Window - самый точный алгоритм.

        Параметры:
            rate: максимально допустимое число событий за интервал
            per: длительность окна (в секундах)
            storage: хранилище (по умолчанию память)
            scope: имя набора лимитов (для метрик)

        Не дает делать burst'ы, строго контролирует rate в скользящем окне.
        """
        return SlidingWindowLimiter(rate, per, storage, scope)

    @staticmethod
    def redis_sliding_window(
        rate: float,
        per: float = 1.0,
        storage: Optional[RedisStorage] = None,
        scope: str = "default"
    ):
        """
        Реализация скользящего окна с использованием Redis (через ZSET).

        Параметры:
            rate: максимум событий за окно
            per: длительность окна в секундах
            storage: RedisStorage с поддержкой eval_script
            scope: префикс для ключей и метрик
        """
        return RedisSlidingWindow(rate, per, storage, scope)

    @staticmethod
    def leaky_bucket(
        rate: float,
        capacity: float,
        storage: Optional[Storage] = None,
        scope: str = "default"
    ):
        """
        Leaky Bucket - сглаживает нагрузку.

        Параметры:
            rate: скорость утечки (токенов в секунду)
            capacity: максимальный объем ведра (лимит накопления)
            storage: хранилище состояния (Redis, память)
            scope: имя набора лимитов (для метрик)

        Хорош когда надо равномерно распределить запросы во времени.
        """
        return LeakyBucketLimiter(rate, capacity, storage, scope)

    @staticmethod
    def adaptive(
        initial_rate: float = 100,
        min_rate: float = 10,
        max_rate: float = 1000,
        increase_step: float = 1.0,
        decrease_factor: float = 0.5,
        error_threshold: float = 0.1,
        window: float = 60.0
    ):
        """
        Adaptive - самонастраивающийся лимитер.

        Параметры:
            initial_rate: стартовая скорость (токенов в секунду)
            min_rate: нижний предел
            max_rate: верхний предел
            increase_step: насколько увеличиваем при низком уровне ошибок
            decrease_factor: во сколько раз уменьшаем при превышении порога ошибок
            error_threshold: доля ошибок, после которой "тормозим"
            window: период анализа статистики (сек)

        Использует AIMD алгоритм: при ошибках уменьшает rate,
        при успехе - увеличивает. Сам подстраивается под нагрузку.
        """
        return AdaptiveLimiter(
            initial_rate,
            min_rate,
            max_rate,
            increase_step,
            decrease_factor,
            error_threshold,
            window
        )

    @staticmethod
    def composite(limiters: List[BaseLimiter]):
        """
        Составной лимитер - комбинирует несколько.

        Параметры:
            limiters: список объектов, реализующих интерфейс Limiter

        Полезно когда нужно ограничить и по минутам и по часам:
            LimiterFactory.composite([
                LimiterFactory.token_bucket(100, per=60),  # 100/мин
                LimiterFactory.token_bucket(1000, per=3600)  # 1000/час
            ])
        """
        return CompositeLimiter(limiters)


class QueueFactory:
    """
    Фабрика для создания очередей.
    Разные очереди под разные задачи.
    """

    @staticmethod
    def priority(
        workers: int = 1,
        max_size: int = 10000,
        priority_fn: Optional[Callable[[Any], int]] = None
    ):
        """
        Приоритетная очередь.

        Параметры:
            workers: количество воркеров
            max_size: максимальный размер очереди
            priority_fn: функция вычисления приоритета (если не задан явно)

        Задачи с высоким priority выполняются первыми.
        """
        return PriorityQueue(workers, max_size, priority_fn)

    @staticmethod
    def fifo(
        workers: int = 1,
        max_size: int = 10000,
        batch_size: int = 1,
        batch_timeout: float = 1.0,
        batch_fn: Optional[Callable[[List[Any]], Any]] = None
    ):
        """
        FIFO очередь с батчингом.

        Параметры:
            workers: количество параллельных воркеров
            max_size: максимальный размер очереди
            batch_size: сколько задач собираем в одну пачку
            batch_timeout: максимум ожидания, пока наберется batch
            batch_fn: функция обработки пачки (если задана, то выполняется вместо отдельных)

        Может накапливать задачи и обрабатывать пачками - экономит на DB/API вызовах.
        """
        return FIFOQueue(workers, max_size, batch_size, batch_timeout, batch_fn)

    @staticmethod
    def delay(
        workers: int = 1,
        max_size: int = 10000
    ):
        """
        Очередь с отложенным выполнением.

        Параметры:
            workers: количество воркеров
            max_size: максимум элементов в очереди

        Можно запланировать задачу на потом.
        """
        return DelayQueue(workers, max_size)

    @staticmethod
    def dedupe(
        workers: int = 1,
        max_size: int = 10000,
        ttl: float = 300.0,
        key_fn: Optional[Callable[[Any], str]] = None
    ):
        """
        Очередь с дедупликацией.

        Параметры:
            workers: количество воркеров
            max_size: максимальный размер очереди
            ttl: сколько секунд хранить ключ в `_seen`
            key_fn: функция генерации ключа для элемента

        Автоматом отсеивает одинаковые задачи.
        """
        return DedupeQueue(workers, max_size, ttl, key_fn)

    @staticmethod
    def broadcast(max_size: int = 10000):
        """
        Broadcast очередь (pub/sub).

        Параметры:
            max_size: максимальный размер очереди для каждого подписчика

        Одна задача уходит всем подписчикам.
        """
        return BroadcastQueue(max_size)


RateLimiter = LimiterFactory
Queue = QueueFactory
