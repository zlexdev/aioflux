from functools import wraps
from typing import Callable, Any
from aioflux.utils.common import now
from aioflux.core.metrics import incr
import asyncio


class CircuitBreakerOpen(Exception):
    """Ошибка — схема разомкнута, вызов заблокирован."""
    pass


class CircuitBreaker:
    """
    Реализация паттерна "Circuit Breaker" (предохранитель).

    Смысл:
    - защищает систему от постоянных неудачных вызовов (например, при падении внешнего API);
    - при множественных ошибках «размыкает цепь» и перестает делать вызовы на время;
    - после таймаута пробует снова в состоянии `half_open`.

    Состояния:
    - closed — всё нормально, вызовы проходят;
    - open — цепь разомкнута, вызовы сразу отклоняются;
    - half_open — тестируем: один вызов проходит, если успешен — возвращаемся в closed.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: float = 60.0,
        expected_exception: type = Exception
    ):
        """
        failure_threshold — сколько подряд ошибок допускается до перехода в `open`
        timeout — сколько секунд держать цепь открытой
        expected_exception — тип исключений, считающихся "ошибками"
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception

        self._failure_count = 0
        self._last_failure_time = 0
        self._state = "closed"
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Обертка для вызова функции через предохранитель.
        Контролирует ошибки и переключает состояние при необходимости.
        """
        async with self._lock:
            if self._state == "open":
                # проверяем, истек ли таймаут
                if now() - self._last_failure_time > self.timeout:
                    self._state = "half_open"
                    self._failure_count = 0
                    await incr("circuit_breaker.half_open")
                else:
                    await incr("circuit_breaker.rejected")
                    raise CircuitBreakerOpen("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)

            async with self._lock:
                # успешный вызов в half_open → возвращаемся в норму
                if self._state == "half_open":
                    self._state = "closed"
                    self._failure_count = 0
                    await incr("circuit_breaker.closed")

            return result

        except self.expected_exception:
            # фиксируем неудачу
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = now()

                if self._failure_count >= self.failure_threshold:
                    self._state = "open"
                    await incr("circuit_breaker.opened")

            raise


def circuit_breaker(
    failure_threshold: int = 5,
    timeout: float = 60.0,
    expected_exception: type = Exception
):
    """
    Декоратор для быстрого применения CircuitBreaker к функции.

    Пример:
        @circuit_breaker(failure_threshold=3, timeout=30)
        async def fetch_data():
            ...
    """
    cb = CircuitBreaker(failure_threshold, timeout, expected_exception)

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            return await cb.call(func, *args, **kwargs)

        wrapper.__circuit_breaker__ = cb
        return wrapper

    return decorator
