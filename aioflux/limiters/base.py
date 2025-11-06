from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseLimiter(ABC):
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
