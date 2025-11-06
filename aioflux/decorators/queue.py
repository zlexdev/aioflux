from functools import wraps
from typing import Optional, Callable, Any
from aioflux.queues.base.base import BaseQueue
from aioflux.queues.fifo import FIFOQueue
import asyncio


def queued(
    queue: Optional[BaseQueue] = None,
    priority: Optional[int] = None,
    priority_fn: Optional[Callable[..., int]] = None,
    workers: int = 1
):
    """
    Декоратор для асинхронных функций:
    отправляет вызовы функции в очередь с приоритетом.

    Зачем:
    - упорядочивает выполнение задач (FIFO или кастомная очередь)
    - регулирует количество воркеров
    - можно задать приоритеты задач

    Параметры:
    queue — экземпляр очереди (по умолчанию FIFOQueue)
    priority — фиксированный приоритет задачи
    priority_fn — функция, возвращающая приоритет по аргументам
    workers — количество параллельных воркеров
    """
    if queue is None:
        queue = FIFOQueue(workers=workers)
        asyncio.create_task(queue.start())

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            result_future = asyncio.Future()

            async def task():
                try:
                    result = await func(*args, **kwargs)
                    result_future.set_result(result)
                except Exception as e:
                    result_future.set_exception(e)

            # вычисляем приоритет
            pri = priority
            if priority_fn:
                pri = priority_fn(*args, **kwargs)

            await queue.put(task, priority=pri or 0)
            return await result_future

        wrapper.__queue__ = queue
        return wrapper

    return decorator


def queued_sync(
    queue: Optional[BaseQueue] = None,
    priority: Optional[int] = None,
    priority_fn: Optional[Callable[..., int]] = None,
    workers: int = 1
):
    """
    Синхронная версия queued-декоратора.

    Можно использовать для обычных функций, чтобы их выполнение
    шло через асинхронную очередь (внутри запускается event loop).

    Пример:
        @queued_sync(workers=2)
        def heavy_task(x):
            time.sleep(1)
            return x * 2
    """
    if queue is None:
        queue = FIFOQueue(workers=workers)
        loop = asyncio.get_event_loop()
        loop.create_task(queue.start())

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            loop = asyncio.get_event_loop()
            result_future = asyncio.Future()

            async def task():
                try:
                    result = func(*args, **kwargs)
                    result_future.set_result(result)
                except Exception as e:
                    result_future.set_exception(e)

            pri = priority
            if priority_fn:
                pri = priority_fn(*args, **kwargs)

            loop.run_until_complete(queue.put(task, priority=pri or 0))
            return loop.run_until_complete(result_future)

        wrapper.__queue__ = queue
        return wrapper

    return decorator
