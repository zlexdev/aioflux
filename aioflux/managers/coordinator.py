import asyncio
import uuid
from typing import Optional

from aioflux.core.metrics import incr
from aioflux.core.storage.redis_ import RedisStorage


class Coordinator:
    """
    Координатор для распределенного лидерства

    Работает через Redis: только один экземпляр процесса может быть «лидером».
    Остальные ждут освобождения блокировки

    Используется для синхронизации нескольких инстансов —
    например, чтобы только один выполнял периодические задачи
    """

    def __init__(
        self,
        storage: RedisStorage,
        lock_name: str = "coordinator_lock",
        ttl: float = 10.0,
        retry_interval: float = 1.0
    ):
        """
        storage — клиент RedisStorage
        lock_name — имя ключа блокировки
        ttl — время жизни блокировки (в секундах)
        retry_interval — как часто пытаться заново стать лидером
        """
        self.storage = storage
        self.lock_name = lock_name
        self.ttl = ttl
        self.retry_interval = retry_interval
        self._instance_id = str(uuid.uuid4())
        self._is_leader = False
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def acquire_leadership(self) -> bool:
        """
        Пытаемся стать лидером.
        Если ключ в Redis свободен или уже принадлежит нам — устанавливаем его с ttl и становимся лидером
        """
        script = """
        local key = KEYS[1]
        local instance = ARGV[1]
        local ttl = tonumber(ARGV[2])

        local current = redis.call('GET', key)
        if not current or current == instance then
            redis.call('SET', key, instance, 'EX', ttl)
            return 1
        end
        return 0
        """

        result = await self.storage.eval_script(
            script,
            [self.lock_name],
            [self._instance_id, int(self.ttl)]
        )

        self._is_leader = result == 1

        # если стали лидером — запускаем поддержание блокировки
        if self._is_leader:
            await incr("coordinator.leader.acquired")
            if not self._heartbeat_task:
                self._heartbeat_task = asyncio.create_task(self._heartbeat())

        return self._is_leader

    async def release_leadership(self) -> None:
        """
        Отпускаем лидерство (удаляем ключ из Redis, если он наш).
        Останавливаем heartbeat.
        """
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        script = """
        local key = KEYS[1]
        local instance = ARGV[1]

        local current = redis.call('GET', key)
        if current == instance then
            redis.call('DEL', key)
            return 1
        end
        return 0
        """

        await self.storage.eval_script(
            script,
            [self.lock_name],
            [self._instance_id]
        )

        self._is_leader = False
        await incr("coordinator.leader.released")

    async def _heartbeat(self) -> None:
        """
        Фоновая задача — продлевает TTL блокировки.
        Если Redis вернул, что ключ уже не наш, теряем лидерство.
        """
        while True:
            try:
                await asyncio.sleep(self.ttl / 2)

                script = """
                local key = KEYS[1]
                local instance = ARGV[1]
                local ttl = tonumber(ARGV[2])

                local current = redis.call('GET', key)
                if current == instance then
                    redis.call('EXPIRE', key, ttl)
                    return 1
                end
                return 0
                """

                result = await self.storage.eval_script(
                    script,
                    [self.lock_name],
                    [self._instance_id, int(self.ttl)]
                )

                if result != 1:
                    # кто-то другой захватил лидерство
                    self._is_leader = False
                    await incr("coordinator.leader.lost")
                    break

                await incr("coordinator.heartbeat")

            except asyncio.CancelledError:
                # нормальное завершение — при release_leadership()
                break

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    async def wait_for_leadership(self) -> None:
        """
        Ждем, пока не станем лидером.
        Периодически пытаемся захватить блокировку.
        """
        while not await self.acquire_leadership():
            await asyncio.sleep(self.retry_interval)
