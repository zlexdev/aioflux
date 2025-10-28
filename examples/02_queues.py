"""
Примеры работы с очередями.
Очереди нужны чтобы складывать задачи и обрабатывать их воркерами.
"""

import asyncio
from aioflux import Queue, queued


async def example_1_priority_queue():
    """
    Пример 1: Приоритетная очередь.
    Задачи с высоким priority выполняются первыми.
    """
    print("\n=== Пример 1: Приоритетная очередь ===\n")
    
    queue = Queue.priority(workers=2)
    await queue.start()
    
    results = []
    
    async def task(name: str, priority: int):
        print(f"Выполняем задачу: {name} (приоритет: {priority})")
        results.append(name)
        await asyncio.sleep(0.2)
    
    # Кидаем задачи в случайном порядке
    await queue.put(lambda: task("низкий-1", 1), priority=1)
    await queue.put(lambda: task("ВЫСОКИЙ", 10), priority=10)
    await queue.put(lambda: task("средний", 5), priority=5)
    await queue.put(lambda: task("низкий-2", 1), priority=1)
    
    # Ждем выполнения
    await asyncio.sleep(1)
    await queue.stop()
    
    print(f"\nПорядок выполнения: {results}")
    print("Видно что высокий приоритет выполнился первым")


async def example_2_fifo_batching():
    """
    Пример 2: FIFO очередь с батчингом.
    Накапливаем задачи и обрабатываем пачками - экономим на вызовах DB/API.
    """
    print("\n=== Пример 2: Батчинг ===\n")
    
    async def process_batch(items):
        """Обработчик батча - получает список элементов"""
        print(f"Обрабатываем батч из {len(items)} элементов: {items}")
        # Тут можно например сделать bulk insert в базу
        await asyncio.sleep(0.1)
    
    # Создаем очередь: батчи по 5 элементов или каждые 2 секунды
    queue = Queue.fifo(
        workers=2,
        batch_size=5,
        batch_timeout=2.0,
        batch_fn=process_batch
    )
    await queue.start()
    
    # Кидаем 12 элементов
    print("Кидаем 12 элементов в очередь:")
    for i in range(12):
        await queue.put(f"item_{i}")
        print(f"  Добавили item_{i}")
        await asyncio.sleep(0.3)
    
    # Ждем обработки
    await asyncio.sleep(3)
    await queue.stop()
    
    print("\nБатчинг помог: вместо 12 вызовов сделали всего 3")


async def example_3_delayed_queue():
    """
    Пример 3: Отложенное выполнение.
    Можно запланировать задачу на потом.
    """
    print("\n=== Пример 3: Отложенное выполнение ===\n")
    
    queue = Queue.delay(workers=1)
    await queue.start()
    
    async def task(name: str):
        print(f"Выполняем: {name} в {asyncio.get_event_loop().time():.1f}")
    
    current_time = asyncio.get_event_loop().time()
    print(f"Текущее время: {current_time:.1f}")
    
    # Планируем задачи с разной задержкой
    await queue.put(lambda: task("через 0.5сек"), delay=0.5)
    await queue.put(lambda: task("через 1.5сек"), delay=1.5)
    await queue.put(lambda: task("через 1.0сек"), delay=1.0)
    
    # Ждем выполнения всех
    await asyncio.sleep(2)
    await queue.stop()


async def example_4_dedupe():
    """
    Пример 4: Дедупликация.
    Одинаковые задачи выполняются только раз.
    """
    print("\n=== Пример 4: Дедупликация ===\n")
    
    executed = []
    
    async def task(item_id: int):
        print(f"Обрабатываем item_{item_id}")
        executed.append(item_id)
        await asyncio.sleep(0.1)
    
    queue = Queue.dedupe(
        workers=2,
        ttl=5.0,  # Помним дубликаты 5 секунд
        key_fn=lambda x: str(x)  # Как вычислять ключ дедупликации
    )
    await queue.start()
    
    # Кидаем одни и те же задачи несколько раз
    print("Кидаем задачи (с дубликатами):")
    for item_id in [1, 2, 1, 3, 2, 1, 4]:
        await queue.put(lambda i=item_id: task(i))
        print(f"  Добавили task для item_{item_id}")
    
    await asyncio.sleep(1)
    await queue.stop()
    
    print(f"\nВыполнено задач: {len(executed)}")
    print(f"Уникальные ID: {sorted(set(executed))}")
    print("Дубликаты были отсеяны")


async def example_5_decorator():
    """
    Пример 5: Декоратор @queued.
    Автоматом кладет вызовы функции в очередь.
    """
    print("\n=== Пример 5: Декоратор @queued ===\n")
    
    queue = Queue.fifo(workers=2)
    await queue.start()
    
    @queued(queue=queue, priority=5)
    async def process_item(item_id: int):
        print(f"Обрабатываем item {item_id}")
        await asyncio.sleep(0.5)
        return f"Результат для {item_id}"
    
    # Делаем несколько вызовов - они встанут в очередь
    print("Запускаем 5 задач:")
    tasks = [process_item(i) for i in range(5)]
    
    # Ждем выполнения всех
    results = await asyncio.gather(*tasks)
    print(f"\nПолучили результаты: {results}")
    
    await queue.stop()


async def main():
    """Запускаем все примеры"""
    examples = [
        example_1_priority_queue,
        example_2_fifo_batching,
        example_3_delayed_queue,
        example_4_dedupe,
        example_5_decorator,
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.5)


if __name__ == "__main__":
    asyncio.run(main())
