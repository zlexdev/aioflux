"""
Сбор и хранение метрик.

Тут считаем все что движется: сколько запросов приняли/отклонили,
какая задержка, сколько задач в очереди и т.д.
"""

from typing import Dict, Optional
from collections import defaultdict
from time import time
import asyncio


class Metrics:
    """
    Хранилище метрик.
    
    Поддерживает три типа:
    - Счетчики (counters) - просто плюсуем
    - Гауджи (gauges) - текущее значение
    - Гистограммы (histograms) - собираем все значения и считаем `перцы` (я так перцентили называть буду)
    """
    
    def __init__(self):
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, list] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def incr(self, name: str, val: float = 1) -> None:
        async with self._lock:
            self._counters[name] += val
    
    async def gauge(self, name: str, val: float) -> None:
        async with self._lock:
            self._gauges[name] = val
    
    async def timing(self, name: str, val: float) -> None:
        """
        Записываем время выполнения.
        Храним последнюю 1000 значений для расчета перцев.
        """
        async with self._lock:
            hist = self._histograms[name]
            hist.append(val)
            # урезаем чтоб гистограмма не разрослась
            if len(hist) > 1000:
                hist.pop(0)
    
    async def get_stats(self) -> Dict:
        """
        Забираем всю статистику разом.
        Для гистограмм считаем p50/p95/p99.
        """
        async with self._lock:
            stats = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {}
            }
            
            # считаем перцы для каждой гистограммы
            for name, vals in self._histograms.items():
                if vals:
                    sorted_vals = sorted(vals)
                    n = len(sorted_vals)
                    stats["histograms"][name] = {
                        "count": n,
                        "mean": sum(sorted_vals) / n,
                        "p50": sorted_vals[int(n * 0.5)],
                        "p95": sorted_vals[int(n * 0.95)],
                        "p99": sorted_vals[int(n * 0.99)],
                    }
            
            return stats
    
    async def reset(self) -> None:
        async with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# глобал инстанс метрик - для юза из любого места
_global_metrics = Metrics()


async def incr(name: str, val: float = 1) -> None:
    """Плюсуем глобальный счетчик"""
    await _global_metrics.incr(name, val)


async def gauge(name: str, val: float) -> None:
    """Устанавливаем глобальный гаудж"""
    await _global_metrics.gauge(name, val)


async def timing(name: str, val: float) -> None:
    """Записываем время в глобальную гистограмму"""
    await _global_metrics.timing(name, val)


async def get_stats() -> Dict:
    """Забираем всю глобальную статистику"""
    return await _global_metrics.get_stats()


class Timer:
    """
    Контекстный менеджер для замера времени
    
    Использование:
        async with Timer("my_operation"):
            await do_something()
    
    Автоматом запишет время выполнения в метрики
    """
    
    def __init__(self, name: str):
        self.name = name
        self.start = 0
    
    async def __aenter__(self):
        self.start = time()
        return self
    
    async def __aexit__(self, *args):
        elapsed = (time() - self.start) * 1000
        await timing(self.name, elapsed)
