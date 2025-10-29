# aioflux

[![PyPI version](https://img.shields.io/pypi/v/aioflux.svg)](https://pypi.org/project/aioflux/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Асинхронная библиотека для управления рейт-лимитами и очередями


## Установка

```bash
pip install aioflux
```

## Быстрый старт

### Базовый rate limiting

```python
from aioflux import LimiterFactory


limiter = LimiterFactory.token_bucket(rate=100, per=60)

if await limiter.acquire("user_123"):
    await process_request()
```

### Использование декоратора

```python
from aioflux import rate_limit


@rate_limit(rate=100, per=60)
async def api_call():
    return await external_api()
```

### Приоритетная очередь

```python
from aioflux import QueueFactory


queue = QueueFactory.priority(workers=5)
await queue.start()

await queue.put(task, priority=10)
```

### Составной лимитер

```python
limiter = LimiterFactory.composite(
    LimiterFactory.token_bucket(rate=100, per=60),
    LimiterFactory.token_bucket(rate=1000, per=3600)
)
```

## Производительность

Token Bucket (MemoryStorage): 1,000,000 ops/sec  
Token Bucket (RedisStorage): 50,000 ops/sec  
Queue throughput: 100,000 tasks/sec  
Latency overhead: <1ms p99  
Memory footprint: <10MB для 1M tracked tokens

## Возможности

### Rate Limiting

Библиотека предоставляет пять алгоритмов ограничения скорости запросов:

**Token Bucket**  
Самый производительный алгоритм. Сложность O(1). Поддерживает burst capacity.  
Производительность: до 1M операций/сек в памяти, до 50K операций/сек через Redis

**Sliding Window**  
Наиболее точный алгоритм. Сложность O(log N). Строгий контроль rate в скользящем окне.  
Не позволяет делать burst'ы

**Leaky Bucket**  
Сглаживает нагрузку. Полезен когда требуется равномерное распределение запросов во времени

**Adaptive**  
Самонастраивающийся лимитер. Использует AIMD алгоритм для автоматической подстройки rate  
на основе error rate и latency

**Composite**  
Позволяет комбинировать несколько лимитеров. Например: 100/минуту И 1000/час одновременно

### Очереди

**Priority Queue**  
Heap-based очередь с приоритетами. Задачи с высоким priority выполняются первыми

**FIFO Queue**  
FIFO очередь с поддержкой батчинга. Может накапливать задачи и обрабатывать пачками  
для оптимизации вызовов к БД или внешним API

**Delay Queue**  
Очередь с отложенным выполнением. Позволяет запланировать задачу на определенное время

**Dedupe Queue**  
Очередь с автоматической дедупликацией. Одинаковые задачи выполняются только один раз

**Broadcast Queue**  
Pub/Sub паттерн. Одна задача отправляется всем подписчикам

### Хранилища

**MemoryStorage**  
Хранение данных в памяти процесса. Максимальная производительность.  
Данные не персистентны. LRU eviction при переполнении.

**RedisStorage**  
Хранение в Redis. Данные персистентны. Поддержка распределенных лимитов.  
Использует Lua скрипты для атомарных операций.

**HybridStorage**  
Двухуровневое хранилище: L1 (память) + L2 (Redis).  
Read-aside кэширование для горячих данных. Write-through для обеспечения консистентности.

### Декораторы

**@rate_limit**  
Автоматическое применение rate limiting к функции.

**@queued**  
Автоматическая постановка вызовов функции в очередь.

**@circuit_breaker**  
Реализация паттерна Circuit Breaker для защиты от каскадных сбоев.

### Дополнительные компоненты

**WorkerPool**  
Пул воркеров с автомасштабированием. Диапазон: min_workers - max_workers. 
Автоматическое scale up при высокой нагрузке, scale down при простое

**Scheduler**  
Планировщик задач. Cron-like функционал для периодического выполнения

**Coordinator**  
Распределенная координация. Leader election через Redis
Реализация распределенных блокировок

**Metrics**  
Система сбора метрик. Поддержка counters, gauges, histograms.  
Экспорт в Prometheus. Консольный вывод для отладки

## Архитектура

### Storage Layer

Три реализации хранилища данных с единым интерфейсом.  
MemoryStorage использует dict с asyncio.Lock для синхронизации.  
RedisStorage использует redis с connection pooling.  
HybridStorage комбинирует оба подхода для оптимальной производительности.

### Rate Limiters

Token Bucket реализован через атомарные операции INCR/DECR.  
Sliding Window использует sorted structures для timestamp фильтрации.  
Adaptive Limiter использует AIMD алгоритм для динамической подстройки rate.

### Queues

Priority Queue построена на asyncio.PriorityQueue с heap структурой.  
FIFO Queue использует asyncio.Queue с батчингом через таймауты.  
Все очереди поддерживают graceful shutdown.

### Metrics

Метрики собираются в реальном времени. Histograms хранят последние 1000 значений  
для вычисления перцентилей. Counters и gauges используют defaultdict для эффективного хранения.

## Примеры

См. директорию `examples/` для подробных примеров использования:

- `01_basic_rate_limiting.py` - Базовые примеры rate limiting
- `02_queues.py` - Работа с очередями
- `03_advanced.py` - Продвинутые сценарии
- `04_redis_distributed.py` - Распределенные лимиты через Redis
- `05_real_world.py` - Реальные сценарии использования

## Тестирование

```bash
python test_basic.py
```

## Лицензия

MIT
