import asyncio
from random import uniform
from typing import Callable


async def backoff(
    func: Callable,
    *args,
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
    **kwargs
):
    """
    Универсальная функция повторных попыток с экспоненциальной задержкой.

    Алгоритм:
    - пробуем вызвать функцию `func`
    - при ошибке из списка `exceptions` ждем и повторяем
    - время ожидания растет по экспоненте: delay *= exponential_base
    - можно добавить джиттер (рандомизация задержки)

    Параметры:
        max_retries — максимум попыток
        base_delay — стартовая задержка
        max_delay — максимум задержки между попытками
        exponential_base — коэффициент роста задержки
        jitter — если True, добавляется случайная вариация
        exceptions — типы исключений, при которых повторяем
    """
    delay = base_delay

    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        except exceptions:
            if attempt == max_retries - 1:
                raise

            # вычисляем задержку
            sleep_time = uniform(0, delay) if jitter else delay
            await asyncio.sleep(sleep_time)

            # увеличиваем задержку по экспоненте, не превышая max_delay
            delay = min(delay * exponential_base, max_delay)


def backoff_decorator(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,)
):
    """
    Декоратор для автоматического повторного вызова функции с backoff.

    Пример:
        @backoff_decorator(max_retries=3, base_delay=0.5)
        async def fetch_data():
            ...
    """
    def decorator(func: Callable) -> Callable:
        async def wrapper(*args, **kwargs):
            return await backoff(
                func, *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
                exceptions=exceptions,
                **kwargs
            )
        return wrapper

    return decorator
