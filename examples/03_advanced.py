"""
Продвинутые примеры - комбинируем разные фичи.
"""

import asyncio
from aioflux import (
    RateLimiter, Queue, rate_limit, queued,
    circuit_breaker, CircuitBreakerOpen,
    get_stats, ConsoleMonitor
)


async def example_1_composite_limiter():
    """
    Пример 1: Составной лимитер.
    Ограничиваем и по минутам и по часам одновременно.
    """
    print("\n=== Пример 1: Составной лимитер ===\n")
    
    # 10 rpm И 50 rph
    limiter = RateLimiter.composite(
        RateLimiter.token_bucket(rate=10, per=60),
        RateLimiter.token_bucket(rate=50, per=3600)
    )
    
    # Проверяем оба лимита
    accepted = 0
    for i in range(15):
        if await limiter.acquire("user_1"):
            accepted += 1
    
    print(f"Приняли {accepted} из 15 запросов")
    print("Оба лимита работают одновременно")


async def example_2_circuit_breaker():
    """
    Пример 2: Circuit Breaker.
    Защищаемся от падающего сервиса - после N ошибок перестаем дергать.
    """
    print("\n=== Пример 2: Circuit Breaker ===\n")
    
    call_count = [0]
    
    @circuit_breaker(failure_threshold=3, timeout=5.0)
    async def unstable_service():
        """Нестабильный сервис - падает первые 5 вызовов"""
        call_count[0] += 1
        print(f"Попытка {call_count[0]}")
        
        if call_count[0] < 6:
            raise Exception("Сервис упал")
        return "OK"
    
    # вызов сервиса
    for i in range(10):
        try:
            result = await unstable_service()
            print(f"  Вызов {i+1}: {result}")
        except CircuitBreakerOpen:
            print(f"  Вызов {i+1}: Circuit breaker открыт - не дергаем сервис")
        except Exception as e:
            print(f"  Вызов {i+1}: Ошибка - {e}")
        await asyncio.sleep(0.5)
    
    print("\ncircuit breaker защитил от лишних вызовов")


async def example_3_full_stack():
    """
    Пример 3: Полный стек.
    Комбинируем rate limiter + queue + circuit breaker.
    """
    print("\n=== Пример 3: Полный стек ===\n")
    
    # Настраиваем rate limiter
    limiter = RateLimiter.token_bucket(rate=5, per=1.0)
    
    # Настраиваем очередь
    queue = Queue.priority(workers=2)
    await queue.start()
    
    # Функция с тремя декораторами
    @rate_limit(limiter=limiter)
    @queued(queue=queue, priority=10)
    @circuit_breaker(failure_threshold=3)
    async def process_request(request_id: int):
        print(f"Обрабатываем запрос {request_id}")
        await asyncio.sleep(0.2)
        return f"Result_{request_id}"
    
    # Делаем кучу запросов
    print("Отправляем 10 запросов:")
    tasks = [process_request(i) for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    successful = sum(1 for r in results if not isinstance(r, Exception))
    print(f"\nУспешно: {successful}/10")
    
    await queue.stop()


async def example_4_adaptive_limiter():
    """
    Пример 4: Адаптивный лимитер.
    Сам подстраивается под нагрузку.
    """
    print("\n=== Пример 4: Адаптивный лимитер ===\n")
    
    limiter = RateLimiter.adaptive(
        initial_rate=10,
        min_rate=5,
        max_rate=20
    )
    
    print("Начальный rate: 10")
    
    # Имитируем успешную работу
    print("\nИмитируем успешные запросы:")
    for i in range(30):
        if await limiter.acquire("service"):
            await limiter.report_success()
        await asyncio.sleep(0.05)
    
    stats = await limiter.get_stats("service")
    print(f"Rate после успехов: {stats['current_rate']:.1f}")
    
    # Имитируем ошибки
    print("\nИмитируем ошибки:")
    for i in range(20):
        await limiter.report_error()
        await asyncio.sleep(0.05)
    
    stats = await limiter.get_stats("service")
    print(f"Rate после ошибок: {stats['current_rate']:.1f}")
    
    print("\nЛимитер сам подстроился под нагрузку")


async def example_5_monitoring():
    """
    Пример 5: Мониторинг метрик.
    Смотрим что происходит в системе.
    """
    print("\n=== Пример 5: Мониторинг ===\n")
    
    # Запускаем консольный монитор
    monitor = ConsoleMonitor(check_interval=2.0)
    await monitor.start()
    
    # Делаем какую-то работу
    limiter = RateLimiter.token_bucket(rate=10, per=1.0)
    
    for i in range(50):
        await limiter.acquire(f"user_{i % 3}")
        await asyncio.sleep(0.05)
    
    # Даем мониторингу показать метрики
    await asyncio.sleep(3)
    await monitor.stop()


async def main():
    """Запускаем примеры"""
    examples = [
        example_1_composite_limiter,
        example_2_circuit_breaker,
        example_3_full_stack,
        example_4_adaptive_limiter,
        example_5_monitoring,
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
