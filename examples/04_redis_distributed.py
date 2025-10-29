"""
Работа с Redis для распределенных лимитов.
Нужно когда у вас несколько инстансов приложения.
"""

import asyncio
from aioflux import LimiterFactory, RedisStorage, HybridStorage


async def example_1_redis_limiter():
    """
    Пример 1: Распределенный лимитер через Redis.
    Лимиты работают на все инстансы приложения.
    """
    print("\n=== Пример 1: Redis лимитер ===\n")
    
    # Создаем Redis хранилище
    try:
        from redis.asyncio import Redis
        redis = Redis.from_url("redis://localhost:6379")
    except ImportError:
        ...
    storage = RedisStorage("redis://localhost:6379")
    
    # Лимитер на 100 запросов в минуту - ОБЩИЙ для всех инстансов
    limiter = LimiterFactory.token_bucket(
        rate=100,
        per=60,
        storage=storage,
        scope="global"  # Общая область
    )
    
    print("Этот лимитер работает на все инстансы приложения")
    print("Если запустить несколько процессов - они все будут видеть один лимит")
    
    # Делаем запросы
    accepted = 0
    for i in range(10):
        if await limiter.acquire("api_endpoint"):
            accepted += 1
    
    print(f"\nПриняли {accepted}/10 запросов")
    print("В Redis хранится текущее состояние токенов")


async def example_2_per_user_redis():
    """
    Пример 2: Лимиты на пользователя через Redis.
    Полезно для multi-tenant приложений.
    """
    print("\n=== Пример 2: Лимиты на пользователя (Redis) ===\n")
    
    storage = RedisStorage("redis://localhost:6379")
    
    # Каждый пользователь имеет свой лимит
    limiter = LimiterFactory.token_bucket(
        rate=10,
        per=60,
        storage=storage,
        scope="user_limit"
    )
    
    # Разные пользователи не влияют друг на друга
    users = ["user_1", "user_2", "user_3"]
    
    for user in users:
        accepted = 0
        for i in range(15):
            if await limiter.acquire(user):
                accepted += 1
        print(f"{user}: {accepted}/15 запросов прошли")


async def example_3_hybrid_storage():
    """
    Пример 3: Гибридное хранилище (Memory + Redis).
    Быстрота памяти + персистентность Redis.
    """
    print("\n=== Пример 3: Гибридное хранилище ===\n")
    
    # L1 (память) - 1000 элементов
    # L2 (Redis) - все остальное
    storage = HybridStorage(
        redis_url="redis://localhost:6379",
        l1_size=1000
    )
    
    limiter = LimiterFactory.token_bucket(
        rate=100,
        per=1.0,
        storage=storage
    )
    
    print("Горячие ключи кэшируются в памяти")
    print("Холодные - хранятся в Redis")
    print("Получаем скорость памяти для популярных ключей")
    
    # Первый запрос идет в Redis
    await limiter.acquire("user_123")
    print("✓ Первый запрос: Memory miss -> Redis")
    
    # Последующие запросы из кэша
    await limiter.acquire("user_123")
    print("✓ Второй запрос: Memory hit (быстро!)")


async def example_4_distributed_system():
    """
    Пример 4: Полноценная распределенная система.
    Несколько типов лимитов работают вместе.
    """
    print("\n=== Пример 4: Распределенная система ===\n")
    
    storage = RedisStorage("redis://localhost:6379")
    
    # Глобальный лимит на API - 1000 запросов в секунду
    global_limiter = LimiterFactory.token_bucket(
        rate=1000,
        per=1.0,
        storage=storage,
        scope="api_global"
    )
    
    # Лимит на пользователя - 10 в секунду
    user_limiter = LimiterFactory.token_bucket(
        rate=10,
        per=1.0,
        storage=storage,
        scope="api_user"
    )
    
    # Лимит на endpoint - 100 в секунду
    endpoint_limiter = LimiterFactory.token_bucket(
        rate=100,
        per=1.0,
        storage=storage,
        scope="api_endpoint"
    )
    
    async def handle_request(user_id: str, endpoint: str):
        """Обработка запроса с тремя уровнями проверок"""
        # Проверяем все три лимита
        if not await global_limiter.acquire("api"):
            return "Global limit exceeded"
        
        if not await endpoint_limiter.acquire(endpoint):
            return f"Endpoint {endpoint} limit exceeded"
        
        if not await user_limiter.acquire(user_id):
            return f"User {user_id} limit exceeded"
        
        return "OK"
    
    # Имитируем запросы
    results = []
    for i in range(20):
        result = await handle_request("user_1", "/api/data")
        results.append(result)
    
    ok_count = sum(1 for r in results if r == "OK")
    print(f"Успешно: {ok_count}/20")
    print("\nВсе три лимита работают через Redis")
    print("Если запустить еще инстанс - он увидит те же лимиты")


async def example_5_stats_monitoring():
    """
    Пример 5: Мониторинг лимитов через Redis.
    """
    print("\n=== Пример 5: Мониторинг ===\n")
    
    storage = RedisStorage("redis://localhost:6379")
    limiter = LimiterFactory.token_bucket(
        rate=50,
        per=1.0,
        burst=75,
        storage=storage
    )
    
    # Делаем несколько запросов
    for i in range(30):
        await limiter.acquire("monitored_service")
    
    # Смотрим статистику
    stats = await limiter.get_stats("monitored_service")
    print(f"Доступно токенов: {stats['available_tokens']:.1f}")
    print(f"Максимум: {stats['max_tokens']}")
    print(f"Скорость пополнения: {stats['refill_rate']:.1f}/сек")
    
    print("\nЭту статистику видят все инстансы")


async def main():
    """
    ВАЖНО: Для запуска этих примеров нужен Redis.
    
    Запуск Redis через Docker:
        docker run -d -p 6379:6379 redis:alpine
    
    Если Redis нет - примеры упадут с ошибкой подключения.
    """
    print("=" * 60)
    print("Примеры с Redis")
    print("=" * 60)
    print("\nВНИМАНИЕ: Для работы нужен запущенный Redis на localhost:6379")
    print("Запустите: docker run -d -p 6379:6379 redis:alpine")
    print()
    
    try:
        examples = [
            example_1_redis_limiter,
            example_2_per_user_redis,
            example_3_hybrid_storage,
            example_4_distributed_system,
            example_5_stats_monitoring,
        ]
        
        for example in examples:
            await example()
            await asyncio.sleep(0.5)
            
    except Exception as e:
        print(f"\nОшибка: {e}")
        print("\nВероятно Redis не запущен.")
        print("Установите и запустите Redis для работы с этими примерами.")


if __name__ == "__main__":
    asyncio.run(main())
