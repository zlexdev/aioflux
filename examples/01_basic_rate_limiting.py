"""
Базовые примеры использования aioflux.
Самые простые сценарии - начни с этого файла.
"""

import asyncio
from aioflux import LimiterFactory, rate_limit


async def example_1_simple_limiter():
    """
    Пример 1: Простейший rate limiter.
    Ограничиваем до 5 запросов в секунду.
    """
    print("\n=== Пример 1: Простой лимитер ===\n")
    
    limiter = LimiterFactory.token_bucket(rate=5, per=1.0)
    
    # Пытаемся сделать 10 запросов
    for i in range(10):
        if await limiter.acquire("user_123"):
            print(f"Запрос {i+1}: прошел ✓")
        else:
            print(f"Запрос {i+1}: отклонен (лимит) ✗")
        await asyncio.sleep(0.1)


async def example_2_decorator():
    """
    Пример 2: Используем декоратор @rate_limit.
    Это удобнее чем вручную вызывать acquire/release.
    """
    print("\n=== Пример 2: Декоратор @rate_limit ===\n")
    
    @rate_limit(rate=3, per=1.0)
    async def api_call(user_id: int):
        """Типичный API вызов с ограничением"""
        print(f"Делаем запрос для user_{user_id}")
        return {"status": "ok", "user_id": user_id}
    
    # Делаем несколько вызовов подряд
    # Первые 3 пройдут сразу, остальные будут ждать
    for i in range(5):
        result = await api_call(user_id=123)
        print(f"  Результат {i+1}: {result}")


async def example_3_burst():
    """
    Пример 3: Burst capacity.
    Позволяем кратковременные всплески нагрузки.
    """
    print("\n=== Пример 3: Burst capacity ===\n")
    
    # 10 запросов в секунду, но можем сделать burst до 20
    limiter = LimiterFactory.token_bucket(rate=10, per=1.0, burst=20)
    
    # Делаем 15 запросов сразу - burst поможет
    print("Делаем 15 запросов подряд:")
    for i in range(15):
        if await limiter.acquire("user_456"):
            print(f"  Запрос {i+1}: OK")
        else:
            print(f"  Запрос {i+1}: REJECT")


async def example_4_per_user():
    """
    Пример 4: Лимиты на каждого пользователя.
    Разные пользователи не влияют друг на друга.
    """
    print("\n=== Пример 4: Лимиты на пользователя ===\n")
    
    limiter = LimiterFactory.token_bucket(rate=3, per=1.0)
    
    # User 1 делает 4 запроса
    print("User 1 делает запросы:")
    for i in range(4):
        if await limiter.acquire("user_1"):
            print(f"  Запрос {i+1} от user_1: OK")
        else:
            print(f"  Запрос {i+1} от user_1: REJECT")
    
    # User 2 делает 4 запроса - его лимиты отдельные
    print("\nUser 2 делает запросы:")
    for i in range(4):
        if await limiter.acquire("user_2"):
            print(f"  Запрос {i+1} от user_2: OK")
        else:
            print(f"  Запрос {i+1} от user_2: REJECT")


async def example_5_stats():
    """
    Пример 5: Смотрим статистику лимитера.
    Можно узнать сколько токенов осталось.
    """
    print("\n=== Пример 5: Статистика ===\n")
    
    limiter = LimiterFactory.token_bucket(rate=10, per=1.0, burst=15)
    
    # Делаем несколько запросов
    for i in range(7):
        await limiter.acquire("user_789")
    
    # Смотрим статистику
    stats = await limiter.get_stats("user_789")
    print(f"Доступно токенов: {stats['available_tokens']:.1f}")
    print(f"Максимум токенов: {stats['max_tokens']}")
    print(f"Скорость пополнения: {stats['refill_rate']:.1f}/сек")


async def main():
    """Запускаем все примеры по очереди"""
    examples = [
        example_1_simple_limiter,
        example_2_decorator,
        example_3_burst,
        example_4_per_user,
        example_5_stats,
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.5)  # Пауза между примерами


if __name__ == "__main__":
    asyncio.run(main())
