"""
Реальные сценарии использования aioflux.
Примеры из продакшена.
"""

import asyncio
from aioflux import LimiterFactory, QueueFactory, rate_limit, queued, circuit_breaker


# Сценарий 1: API Gateway
# Нужно ограничить нагрузку на backend сервисы

class APIGateway:
    """API Gateway с rate limiting и circuit breaker"""
    
    def __init__(self):
        # Глобальный лимит на весь API
        self.global_limiter = LimiterFactory.token_bucket(rate=1000, per=1.0)
        
        # Лимит на пользователя: 10 запросов в секунду, burst до 20
        self.user_limiter = LimiterFactory.token_bucket(rate=10, per=1.0, burst=20)
        
        # Лимит на IP адрес (защита от DDoS)
        self.ip_limiter = LimiterFactory.sliding_window(rate=50, per=1.0)
    
    async def handle_request(self, user_id: str, ip: str, endpoint: str):
        """Обработка запроса с несколькими уровнями лимитов"""
        
        # Проверяем глобальный лимит
        if not await self.global_limiter.acquire("global"):
            return {"error": "Service overloaded"}, 503
        
        # Проверяем лимит на IP
        if not await self.ip_limiter.acquire(ip):
            return {"error": "Too many requests from your IP"}, 429
        
        # Проверяем лимит на пользователя
        if not await self.user_limiter.acquire(user_id):
            return {"error": "Rate limit exceeded"}, 429
        
        # Все проверки прошли - обрабатываем запрос
        return await self.process_request(endpoint)
    
    @circuit_breaker(failure_threshold=5, timeout=30)
    async def process_request(self, endpoint: str):
        """Обработка с circuit breaker - защищаемся от падающего бэкенда"""
        # Тут идем в реальный backend
        await asyncio.sleep(0.01)  # Имитация работы
        return {"status": "ok"}, 200


# Сценарий 2: Background Job Processor
# Обрабатываем задачи с приоритетами и батчингом

class JobProcessor:
    """Обработчик фоновых задач"""
    
    def __init__(self):
        # Приоритетная очередь для критичных задач
        self.critical_queue = QueueFactory.priority(workers=10)
        
        # FIFO очередь с батчингом для массовых операций
        self.bulk_queue = QueueFactory.fifo(
            workers=5,
            batch_size=100,
            batch_timeout=5.0,
            batch_fn=self.process_bulk_batch
        )
    
    async def start(self):
        """Запуск процессора"""
        await self.critical_queue.start()
        await self.bulk_queue.start()
    
    async def stop(self):
        """Остановка процессора"""
        await self.critical_queue.stop()
        await self.bulk_queue.stop()
    
    async def submit_email(self, email_data: dict, critical: bool = False):
        """Отправка email"""
        if critical:
            # Критичные письма (восстановление пароля) - в приоритетную очередь
            await self.critical_queue.put(
                lambda: self.send_email(email_data),
                priority=10
            )
        else:
            # Обычные письма - в батчинг
            await self.bulk_queue.put(email_data)
    
    async def send_email(self, email_data: dict):
        """Отправка одного письма"""
        print(f"Отправляем критичное письмо {email_data['to']}")
        await asyncio.sleep(0.1)
    
    async def process_bulk_batch(self, batch: list):
        """Массовая отправка - эффективнее чем по одному"""
        print(f"Массовая отправка {len(batch)} писем через API")
        # Тут один вызов в email API вместо N вызовов
        await asyncio.sleep(0.2)


# Сценарий 3: External API Client
# Клиент для внешнего API с rate limiting

class ExternalAPIClient:
    """Клиент для внешнего API с лимитами"""
    
    def __init__(self):
        # API имеет лимиты: 100 запросов в минуту и 1000 в час
        self.limiter = LimiterFactory.composite(
            LimiterFactory.token_bucket(rate=100, per=60, burst=120),
            LimiterFactory.token_bucket(rate=1000, per=3600)
        )
        
        # Очередь с дедупликацией - не дублируем запросы
        self.request_queue = QueueFactory.dedupe(workers=5, ttl=60.0)
    
    async def start(self):
        await self.request_queue.start()
    
    @rate_limit(rate=100, per=60)
    @circuit_breaker(failure_threshold=5, timeout=60)
    async def fetch_user(self, user_id: int):
        """Получение данных пользователя"""
        print(f"Запрашиваем пользователя {user_id}")
        await asyncio.sleep(0.1)
        return {"id": user_id, "name": f"User_{user_id}"}
    
    async def fetch_user_cached(self, user_id: int):
        """Запрос с дедупликацией - одинаковые запросы не дублируются"""
        await self.request_queue.put(lambda: self.fetch_user(user_id))


# Сценарий 4: Data Pipeline
# Обработка данных с адаптивным rate limiting

class DataPipeline:
    """Пайплайн обработки данных"""
    
    def __init__(self):
        # Адаптивный лимитер - подстраивается под нагрузку БД
        self.db_limiter = LimiterFactory.adaptive(
            initial_rate=100,
            min_rate=10,
            max_rate=500,
            error_threshold=0.05  # Если >5% ошибок - снижаем нагрузку
        )
        
        # Батчинг для вставки в БД
        self.insert_queue = QueueFactory.fifo(
            workers=3,
            batch_size=1000,
            batch_timeout=2.0,
            batch_fn=self.bulk_insert
        )
    
    async def start(self):
        await self.insert_queue.start()
    
    async def process_record(self, record: dict):
        """Обработка одной записи"""
        # Проверяем лимит на БД
        if not await self.db_limiter.acquire("database"):
            # Если БД перегружена - ждем
            await asyncio.sleep(0.1)
            return await self.process_record(record)
        
        try:
            # Кладем в очередь на вставку
            await self.insert_queue.put(record)
            await self.db_limiter.report_success()
        except Exception as e:
            # При ошибке лимитер сам снизит rate
            await self.db_limiter.report_error()
            raise
    
    async def bulk_insert(self, records: list):
        """Массовая вставка в БД"""
        print(f"Вставляем {len(records)} записей в БД")
        # Один запрос вместо 1000
        await asyncio.sleep(0.5)


# Демонстрация работы

async def demo_api_gateway():
    """Демонстрация API Gateway"""
    print("\n=== API Gateway Demo ===\n")
    
    gateway = APIGateway()
    
    # Имитируем запросы от разных пользователей
    for i in range(15):
        user = f"user_{i % 3}"  # 3 пользователя
        ip = f"192.168.1.{i % 5}"  # 5 IP адресов
        
        response, status = await gateway.handle_request(user, ip, "/api/data")
        print(f"Request {i+1} from {user} ({ip}): {status}")
        await asyncio.sleep(0.05)


async def demo_job_processor():
    """Демонстрация Job Processor"""
    print("\n=== Job Processor Demo ===\n")
    
    processor = JobProcessor()
    await processor.start()
    
    # Отправляем критичное письмо
    await processor.submit_email({
        "to": "user@example.com",
        "subject": "Password Reset"
    }, critical=True)
    
    # Отправляем пачку обычных писем
    for i in range(250):
        await processor.submit_email({
            "to": f"user{i}@example.com",
            "subject": "Newsletter"
        })
    
    await asyncio.sleep(3)
    await processor.stop()


async def demo_data_pipeline():
    print("\n=== Data Pipeline Demo ===\n")
    
    pipeline = DataPipeline()
    await pipeline.start()
    
    for i in range(5000):
        await pipeline.process_record({"id": i, "data": f"value_{i}"})
        if i % 1000 == 0:
            print(f"Обработано {i} записей")
    
    await asyncio.sleep(5)


async def main():
    await demo_api_gateway()
    await demo_job_processor()
    await demo_data_pipeline()


if __name__ == "__main__":
    asyncio.run(main())
