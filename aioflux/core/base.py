"""
Базовые API
Тут живут основные классы, от которых наследуются все остальное
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict
from dataclasses import dataclass
from time import time


@dataclass
class Token:
    key: str
    value: float
    expires: float


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


class Limiter(ABC):
    """
    Базовый класс для rate limiter'ов.
    Главная задача - контролировать скорость запросов.
    """
    
    @abstractmethod
    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Пытаемся взять токены.
        Если удалось - возвращаем True, если лимит исчерпан - False.
        """
        pass
    
    @abstractmethod
    async def release(self, key: str, tokens: float = 1) -> None:
        """Возвращаем токены обратно (не все лимитеры это поддерживают)"""
        pass
    
    @abstractmethod
    async def get_stats(self, key: str) -> Dict[str, Any]:
        """Получаем статистику по конкретному ключу"""
        pass


class QueueBase(ABC):
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


def now() -> float:
    """Текущее время в секундах - просто обертка над time()"""
    return time()
