import asyncio
from typing import Any, Dict

from aioflux.utils.common import now
from aioflux.limiters.base import BaseLimiter
from aioflux.core.metrics import gauge, incr


class AdaptiveLimiter(BaseLimiter):
    """
    Адаптивный лимитер — динамически подстраивает скорость под ошибки и нагрузку.

    Основная идея:
    - при успешных запросах постепенно увеличивает допустимую скорость (rate)
    - при частых отказах — резко снижает (умножает на decrease_factor)
    - работает по принципу токен-бакета, но с авто-регулировкой

    Используется для автоподстройки под внешние ограничения API или нестабильные системы.
    """

    def __init__(
        self,
        initial_rate: float = 100,
        min_rate: float = 10,
        max_rate: float = 1000,
        increase_step: float = 1.0,
        decrease_factor: float = 0.5,
        error_threshold: float = 0.1,
        window: float = 60.0
    ):
        """
        initial_rate — стартовая скорость (токенов в секунду)
        min_rate — нижний предел
        max_rate — верхний предел
        increase_step — насколько увеличиваем при низком уровне ошибок
        decrease_factor — во сколько раз уменьшаем при превышении порога ошибок
        error_threshold — доля ошибок, после которой "тормозим"
        window — период анализа статистики (сек)
        """
        self.current_rate = initial_rate
        self.min_rate = min_rate
        self.max_rate = max_rate
        self.increase_step = increase_step
        self.decrease_factor = decrease_factor
        self.error_threshold = error_threshold
        self.window = window

        self._success_count = 0
        self._error_count = 0
        self._last_adjust = now() - window
        self._tokens = initial_rate
        self._last_refill = now()
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, tokens: float = 1) -> bool:
        """
        Проверка и выдача токенов.
        Успешное получение = "accepted", иначе "rejected".
        """
        async with self._lock:
            current = now()

            # пополняем токены со временем
            elapsed = current - self._last_refill
            self._tokens = min(
                self.current_rate,
                self._tokens + elapsed * self.current_rate
            )
            self._last_refill = current

            # хватает токенов — успех
            if self._tokens >= tokens:
                self._tokens -= tokens
                self._success_count += 1
                await self._adjust_rate()
                await incr("limiter.adaptive.accepted")
                return True

            # не хватило — отказ
            self._error_count += 1
            await self._adjust_rate()
            await incr("limiter.adaptive.rejected")
            return False

    async def _adjust_rate(self) -> None:
        """
        Периодическая корректировка текущей скорости.
        Считаем долю ошибок и либо увеличиваем, либо уменьшаем rate.
        """
        current = now()
        if current - self._last_adjust < self.window:
            return

        total = self._success_count + self._error_count
        if total == 0:
            return

        error_rate = self._error_count / total

        if error_rate > self.error_threshold:
            # слишком много ошибок → понижаем скорость
            self.current_rate = max(
                self.min_rate,
                self.current_rate * self.decrease_factor
            )
        else:
            # ошибок мало → можно ускориться
            self.current_rate = min(
                self.max_rate,
                self.current_rate + self.increase_step
            )

        await gauge("limiter.adaptive.rate", self.current_rate)

        self._success_count = 0
        self._error_count = 0
        self._last_adjust = current

    async def report_error(self) -> None:
        """
        Вручную сообщить об ошибке (влияет на адаптацию скорости)
        """
        async with self._lock:
            self._error_count += 1
            await self._adjust_rate()

    async def report_success(self) -> None:
        """
        Вручную сообщить об успешной операции
        """
        async with self._lock:
            self._success_count += 1
            await self._adjust_rate()

    async def release(self, key: str, tokens: float = 1) -> None:
        """
        Возвращает токены обратно (при отмене операции)
        """
        async with self._lock:
            self._tokens = min(self.current_rate, self._tokens + tokens)

    async def get_stats(self, key: str) -> Dict[str, Any]:
        """Возвращает состояние адаптивного лимитера."""
        async with self._lock:
            return {
                "current_rate": self.current_rate,
                "min_rate": self.min_rate,
                "max_rate": self.max_rate,
                "available_tokens": self._tokens,
                "success_count": self._success_count,
                "error_count": self._error_count
            }
