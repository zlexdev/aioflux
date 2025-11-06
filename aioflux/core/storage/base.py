from abc import ABC, abstractmethod
from typing import Any, Optional


class Storage(ABC):
    """
    Базовый интерфейс для хранилища данных.
    """

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Достаем значение по ключу"""
        pass

    @abstractmethod
    async def set(self, key: str, val: Any, ttl: Optional[float] = None) -> None:
        """Сохраняем значение, можно указать время жизни"""
        pass

    @abstractmethod
    async def incr(self, key: str, delta: float = 1) -> float:
        """Увеличиваем счетчик атомарно"""
        pass

    @abstractmethod
    async def decr(self, key: str, delta: float = 1) -> float:
        """Уменьшаем счетчик атомарно"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Удаляем ключ нафиг"""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Проверяем есть ли ключ"""
        pass
