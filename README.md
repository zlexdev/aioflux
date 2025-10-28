# aioflux

Асинхронная библиотека для управления рейт-лимитами и очередями

## Возможности

- Рейт-лимитинг с 5 алгоритмами
- Очереди с приоритетами и батчингом
- Декораторы
- Поддержка Redis
- Сбор метрик и мониторинг
- Circuit breaker паттерн

## Производительность

Token Bucket: 1M ops/sec в памяти, 50K ops/sec через Redis  
Queue throughput: 100K tasks/sec  
Latency: <1ms p99

## Установка

```bash
pip install -r requirements.txt
pip install -e .
```

## Быстрый старт

```python
from aioflux import RateLimiter, rate_limit

# Простой лимитер
limiter = RateLimiter.token_bucket(rate=100, per=60)
if await limiter.acquire("user_123"):
    await process_request()

# Через декоратор
@rate_limit(rate=100, per=60)
async def api_call():
    pass
```

## Документация

См. директорию `docs/` для подробной документации:
- `docs/README.md` - Обзор возможностей
- `docs/API.md` - Технический API reference

## Примеры

В директории `examples/` находятся примеры:
- `01_basic_rate_limiting.py` - Базовые примеры
- `02_queues.py` - Очереди
- `03_advanced.py` - Продвинутые сценарии
- `05_real_world.py` - Реальные сценарии

## Тесты

```bash
python tests/test_basic.py
```

## Лицензия

MIT
