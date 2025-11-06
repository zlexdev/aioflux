from abc import ABC, abstractmethod
from typing import Any


class BaseQueue(ABC):
    """
    Базовый интерфейс для всех очередей.
    Очереди нужны чтобы складывать задачи и обрабатывать их воркерами.
    """

    @abstractmethod
    async def put(self, item: Any, priority: int = 0) -> None:
        """Кладем задачу в очередь"""
        pass

    @abstractmethod
    async def get(self) -> Any:
        """Достаем задачу из очереди"""
        pass

    @abstractmethod
    async def size(self) -> int:
        """Смотрим сколько задач в очереди"""
        pass

    @abstractmethod
    async def start(self) -> None:
        """Запускаем воркеров"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Останавливаем все нафиг"""
        pass
