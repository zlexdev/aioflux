from typing import Dict, Any
from aioflux.core.metrics import get_stats
import asyncio


class Monitor:
    """
    Базовый монитор метрик.

    Периодически опрашивает глобальные метрики (`get_stats()`)
    и передаёт их в метод `_report`, который реализуют наследники.
    """

    def __init__(self, check_interval: float = 10.0):
        """
        check_interval — как часто собирать и выводить метрики (в секундах)
        """
        self.check_interval = check_interval
        self._running = False
        self._task = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            await self._task

    async def _monitor_loop(self) -> None:
        """
        Основной цикл — периодически собирает и передаёт метрики.
        """
        while self._running:
            stats = await get_stats()
            await self._report(stats)
            await asyncio.sleep(self.check_interval)

    async def _report(self, stats: Dict[str, Any]) -> None:
        """
        Абстрактный метод для вывода или экспорта метрик.
        Переопределяется в потомках.
        """
        pass


class ConsoleMonitor(Monitor):
    """
    Монитор, печатающий метрики в консоль.
    Подходит для отладки или локального тестирования.
    """

    async def _report(self, stats: Dict[str, Any]) -> None:
        print("\n=== AioFlux Metrics ===")

        if stats.get("counters"):
            print("\nCounters:")
            for name, value in stats["counters"].items():
                print(f"  {name}: {value}")

        if stats.get("gauges"):
            print("\nGauges:")
            for name, value in stats["gauges"].items():
                print(f"  {name}: {value}")

        if stats.get("histograms"):
            print("\nHistograms:")
            for name, hist in stats["histograms"].items():
                print(f"  {name}:")
                print(f"    count: {hist['count']}")
                print(f"    mean: {hist['mean']:.2f}ms")
                print(f"    p50: {hist['p50']:.2f}ms")
                print(f"    p95: {hist['p95']:.2f}ms")
                print(f"    p99: {hist['p99']:.2f}ms")


class PrometheusExporter:
    """
    Экспортер метрик в формате Prometheus.

    Запускает HTTP-сервер на указанном порту и отдаёт
    `/metrics` в виде текстовых метрик для сбора Prometheus.
    """

    def __init__(self, port: int = 9090):
        """
        port — порт для экспорта метрик (по умолчанию 9090)
        """
        self.port = port
        self._app = None

    async def start(self) -> None:
        """Запускает aiohttp-сервер с эндпоинтом /metrics."""
        from aiohttp import web

        async def metrics_handler(request):
            stats = await get_stats()
            lines = []

            for name, value in stats.get("counters", {}).items():
                lines.append(f'{name.replace(".", "_")}_total {value}')

            for name, value in stats.get("gauges", {}).items():
                lines.append(f'{name.replace(".", "_")} {value}')

            for name, hist in stats.get("histograms", {}).items():
                prefix = name.replace(".", "_")
                lines.append(f'{prefix}_count {hist["count"]}')
                lines.append(f'{prefix}_mean {hist["mean"]}')
                lines.append(f'{prefix}_p50 {hist["p50"]}')
                lines.append(f'{prefix}_p95 {hist["p95"]}')
                lines.append(f'{prefix}_p99 {hist["p99"]}')

            return web.Response(text="\n".join(lines))

        self._app = web.Application()
        self._app.router.add_get("/metrics", metrics_handler)

        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
