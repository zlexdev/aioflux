# API Reference

Техническая документация по всем публичным интерфейсам библиотеки.

## Rate Limiters

### TokenBucketLimiter

```python
TokenBucketLimiter(rate: float, per: float = 1.0, burst: float = None,
                   storage: Storage = None, scope: str = "default")
```

Параметры:
- `rate` - количество токенов выдаваемых за период
- `per` - длительность периода в секундах
- `burst` - максимальная емкость корзины (по умолчанию = rate)
- `storage` - хранилище данных (по умолчанию MemoryStorage)
- `scope` - область видимости лимитера

Методы:

**acquire(key: str, tokens: float = 1) -> bool**  
Попытка получить указанное количество токенов. Возвращает True при успехе, False при исчерпании лимита.

**release(key: str, tokens: float = 1) -> None**  
Возврат токенов в корзину. Полезно при отмене операции.

**get_stats(key: str) -> Dict[str, Any]**  
Получение статистики по ключу. Возвращает: available_tokens, max_tokens, refill_rate, last_update.

Алгоритм:
1. Вычисляется количество новых токенов: elapsed_time * refill_rate
2. Текущий баланс = min(burst, old_balance + new_tokens)
3. Если баланс >= requested_tokens: выдаем токены, иначе отклоняем

Сложность: O(1)  
Lock-free: Нет (использует asyncio.Lock)

### SlidingWindowLimiter

```python
SlidingWindowLimiter(rate: float, per: float = 1.0,
                     storage: Storage = None, scope: str = "default")
```

Параметры:
- `rate` - максимальное количество запросов в окне
- `per` - размер окна в секундах
- `storage` - хранилище данных
- `scope` - область видимости

Методы: аналогичны TokenBucketLimiter.

Алгоритм:
1. Удаляются все timestamps старше (now - window_size)
2. Если количество оставшихся timestamps < rate: добавляем новый timestamp
3. Иначе отклоняем запрос

Сложность: O(log N) для memory, O(1) для Redis (через ZREMRANGEBYSCORE)  
Точность: Максимальная - учитывает каждый запрос индивидуально

### LeakyBucketLimiter

```python
LeakyBucketLimiter(rate: float, capacity: float,
                   storage: Storage = None, scope: str = "default")
```

Параметры:
- `rate` - скорость утечки токенов в секунду
- `capacity` - емкость корзины
- `storage` - хранилище данных
- `scope` - область видимости

Алгоритм:
1. Вычисляется объем утекших токенов: elapsed_time * leak_rate
2. Текущий уровень = max(0, old_level - leaked)
3. Если level + requested <= capacity: добавляем, иначе отклоняем

Особенность: сглаживает burst'ы, обеспечивает равномерную нагрузку.

### AdaptiveLimiter

```python
AdaptiveLimiter(initial_rate: float = 100, min_rate: float = 10,
                max_rate: float = 1000, increase_step: float = 1.0,
                decrease_factor: float = 0.5, error_threshold: float = 0.1,
                window: float = 60.0)
```

Параметры:
- `initial_rate` - начальный rate
- `min_rate` / `max_rate` - границы rate
- `increase_step` - шаг увеличения при успехе
- `decrease_factor` - множитель уменьшения при ошибке
- `error_threshold` - порог error rate для уменьшения
- `window` - окно для расчета error rate

Методы:

**report_success() -> None**  
Сообщить об успешной операции. Увеличивает счетчик успехов.

**report_error() -> None**  
Сообщить об ошибке. Увеличивает счетчик ошибок.

Алгоритм AIMD:
1. Каждые `window` секунд вычисляется error_rate = errors / (successes + errors)
2. Если error_rate > threshold: rate *= decrease_factor (multiplicative decrease)
3. Иначе: rate += increase_step (additive increase)
4. Rate ограничивается границами [min_rate, max_rate]

### CompositeLimiter

```python
CompositeLimiter(limiters: List[Limiter])
```

Комбинирует несколько лимитеров. Запрос проходит только если ВСЕ лимитеры разрешили.

Сложность: O(N) где N - количество лимитеров.

## Queues

### PriorityQueue

```python
PriorityQueue(workers: int = 1, max_size: int = 10000,
              priority_fn: Callable[[Any], int] = None)
```

Параметры:
- `workers` - количество воркеров
- `max_size` - максимальный размер очереди
- `priority_fn` - функция вычисления приоритета

Методы:

**put(item: Any, priority: int = None) -> None**  
Добавить элемент в очередь с указанным приоритетом.

**get() -> Any**  
Извлечь элемент с наивысшим приоритетом.

**start() -> None**  
Запустить воркеров.

**stop() -> None**  
Остановить очередь. Graceful shutdown - дожидается завершения текущих задач.

Структура данных: heapq (binary heap)  
Сложность put: O(log N)  
Сложность get: O(log N)

### FIFOQueue

```python
FIFOQueue(workers: int = 1, max_size: int = 10000, batch_size: int = 1,
          batch_timeout: float = 1.0, batch_fn: Callable = None)
```

Параметры:
- `batch_size` - размер батча
- `batch_timeout` - максимальное время ожидания батча
- `batch_fn` - функция обработки батча

Алгоритм батчинга:
1. Накапливаем элементы до достижения batch_size
2. Если прошло batch_timeout: отправляем неполный батч
3. Вызываем batch_fn со списком элементов

Использование: Оптимизация bulk операций с БД/API.

### DelayQueue

```python
DelayQueue(workers: int = 1, max_size: int = 10000)
```

Методы:

**put(item: Any, delay: float = 0) -> None**  
Добавить задачу с задержкой в секундах.

Структура данных: heapq упорядоченный по execute_at timestamp.  
Воркеры ждут до execute_at перед извлечением задачи.

### DedupeQueue

```python
DedupeQueue(workers: int = 1, max_size: int = 10000, ttl: float = 300.0,
            key_fn: Callable[[Any], str] = None)
```

Параметры:
- `ttl` - время жизни записи о дедупликации
- `key_fn` - функция вычисления ключа дедупликации

Алгоритм:
1. Вычисляется ключ через key_fn (по умолчанию md5 hash)
2. Если ключ уже есть в seen set: отклоняем
3. Иначе добавляем в очередь и в seen set
4. Через ttl секунд ключ удаляется из seen set

## Storage

### MemoryStorage

```python
MemoryStorage(max_size: int = 100000)
```

Методы:

**get(key: str) -> Optional[Any]**  
**set(key: str, val: Any, ttl: float = None) -> None**  
**incr(key: str, delta: float = 1) -> float**  
**decr(key: str, delta: float = 1) -> float**  
**delete(key: str) -> None**  
**exists(key: str) -> bool**

TTL реализован через отдельный dict с expiry timestamps.  
Cleanup выполняется при каждом get/exists.  
LRU eviction при достижении max_size.

### RedisStorage

```python
RedisStorage(url: str = "redis://localhost", pool_size: int = 10)
```

Connection pooling через redis.  
Использует pipeline для батчинга команд.  
Lua скрипты для атомарных операций.

**eval_script(script: str, keys: list, args: list) -> Any**  
Выполнение Lua скрипта в Redis.

### HybridStorage

```python
HybridStorage(redis_url: str = "redis://localhost", l1_size: int = 10000)
```

Алгоритм кэширования:

**get:**
1. Проверяем L1 (memory)
2. При miss идем в L2 (redis)
3. Кэшируем в L1 с TTL=60 сек

**set:**
1. Пишем в L1 (TTL = min(requested_ttl, 60))
2. Пишем в L2 (TTL = requested_ttl)

**incr/decr:**
1. Инвалидируем L1
2. Выполняем в L2

## Decorators

### @rate_limit

```python
@rate_limit(rate: float = None, per: float = 1.0, burst: float = None,
            strategy: str = "token_bucket", storage: Storage = None,
            scope: str = "default", key_fn: Callable = None,
            limiter: Limiter = None)
```

Параметры:
- `key_fn` - функция вычисления ключа из аргументов функции
- `limiter` - использовать существующий limiter вместо создания нового

По умолчанию ключ = `module.function_name`.

Поведение: При отклонении лимитером функция ждет (sleep loop) до освобождения токена.

### @queued

```python
@queued(queue: QueueBase = None, priority: int = None,
        priority_fn: Callable = None, workers: int = 1)
```

Оборачивает функцию так что каждый вызов ставится в очередь.  
Возвращает Future который резолвится после выполнения в очереди.

### @circuit_breaker

```python
@circuit_breaker(failure_threshold: int = 5, timeout: float = 60.0,
                 expected_exception: type = Exception)
```

Состояния:
- closed - нормальная работа
- open - слишком много ошибок, все запросы отклоняются
- half_open - пробуем восстановиться

Переходы:
1. closed -> open: после failure_threshold ошибок
2. open -> half_open: через timeout секунд
3. half_open -> closed: при успешном запросе
4. half_open -> open: при ошибке

## Managers

### WorkerPool

```python
WorkerPool(min_workers: int = 1, max_workers: int = 10,
           scale_up_threshold: float = 0.8,
           scale_down_threshold: float = 0.2,
           check_interval: float = 5.0)
```

**submit(func: Callable, *args, **kwargs) -> Any**  
Отправить задачу в пул. Возвращает результат выполнения.

Алгоритм масштабирования:
1. Каждые check_interval секунд вычисляется load = queue_size / worker_count
2. Если load > scale_up_threshold: добавляем воркер
3. Если load < scale_down_threshold: удаляем воркер
4. Количество воркеров ограничено [min_workers, max_workers]

### Scheduler

```python
scheduler = Scheduler()

@scheduler.every(seconds=None, minutes=None, hours=None, name=None)
async def task():
    pass

await scheduler.start()
```

Реализация: Event loop с проверкой next_run timestamps.  
Точность: ±0.1 секунды.

### Coordinator

```python
Coordinator(storage: RedisStorage, lock_name: str = "coordinator_lock",
            ttl: float = 10.0, retry_interval: float = 1.0)
```

**acquire_leadership() -> bool**  
Попытка стать лидером. Использует Redis SET NX EX для атомарности.

**release_leadership() -> None**  
Отказ от лидерства.

**is_leader -> bool**  
Проверка текущего статуса.

Heartbeat: Каждые ttl/2 секунд продлевается аренда лидерства.  
При сбое лидера через ttl секунд другой инстанс может захватить лидерство.

## Metrics

**incr(name: str, val: float = 1) -> None**  
Увеличить счетчик.

**gauge(name: str, val: float) -> None**  
Установить значение gauge.

**timing(name: str, val: float) -> None**  
Записать время выполнения в миллисекундах.

**get_stats() -> Dict**  
Получить всю статистику.

Формат ответа:
```python
{
    "counters": {"limiter.accepted": 150, "limiter.rejected": 10},
    "gauges": {"queue.size": 5, "limiter.tokens": 7.5},
    "histograms": {
        "queue.worker.0": {
            "count": 100,
            "mean": 15.3,
            "p50": 12.0,
            "p95": 45.0,
            "p99": 89.0
        }
    }
}
```

### PrometheusExporter

```python
exporter = PrometheusExporter(port=9090)
await exporter.start()
```

Создает HTTP endpoint /metrics в формате Prometheus.  
Экспортирует все counters, gauges, histograms.

## Utilities

### backoff

```python
result = await backoff(func, *args, max_retries=5, base_delay=1.0,
                       max_delay=60.0, exponential_base=2.0,
                       jitter=True, exceptions=(Exception,), **kwargs)
```

Экспоненциальный backoff с jitter.  
Задержка: min(base_delay * (exponential_base ** attempt), max_delay).  
Jitter: случайная задержка в диапазоне [0, computed_delay].

### BatchCollector

```python
collector = BatchCollector(batch_size=100, timeout=1.0, callback=process_batch)
await collector.add(item)
```

Автоматическое батчинг. Флашит когда:
1. Накоплено batch_size элементов
2. Прошло timeout секунд с последнего flush

## Thread Safety

Все компоненты thread-safe через asyncio.Lock.  
Redis операции атомарны через Lua scripts.  
Memory storage использует lock для всех мутирующих операций.

## Performance Notes

1. MemoryStorage предпочтительнее для single-process приложений
2. RedisStorage обязателен для distributed rate limiting
3. HybridStorage оптимален для read-heavy workloads
4. Token Bucket быстрее Sliding Window на ~10x
5. Batch processing снижает overhead на ~90% для bulk операций
