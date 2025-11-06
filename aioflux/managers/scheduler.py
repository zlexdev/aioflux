from typing import Callable, Dict, Optional, List
from aioflux.utils.common import now
from aioflux.core.metrics import incr
import asyncio
from dataclasses import dataclass


@dataclass
class Job:
    func: Callable
    interval: float
    next_run: float
    name: str


class Scheduler:
    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def every(
        self,
        seconds: Optional[float] = None,
        minutes: Optional[float] = None,
        hours: Optional[float] = None,
        name: Optional[str] = None
    ):
        interval = 0
        if seconds:
            interval += seconds
        if minutes:
            interval += minutes * 60
        if hours:
            interval += hours * 3600
        
        def decorator(func: Callable) -> Callable:
            job_name = name or f"{func.__module__}.{func.__name__}"
            job = Job(
                func=func,
                interval=interval,
                next_run=now() + interval,
                name=job_name
            )
            self._jobs[job_name] = job
            return func
        
        return decorator
    
    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
    
    async def stop(self) -> None:
        self._running = False
        if self._task:
            await self._task
    
    async def _run(self) -> None:
        while self._running:
            current = now()
            
            for job in list(self._jobs.values()):
                if current >= job.next_run:
                    asyncio.create_task(self._execute_job(job))
                    job.next_run = current + job.interval
            
            await asyncio.sleep(0.1)
    
    async def _execute_job(self, job: Job) -> None:
        try:
            if asyncio.iscoroutinefunction(job.func):
                await job.func()
            else:
                job.func()
            await incr(f"scheduler.job.{job.name}.success")
        except Exception as e:
            await incr(f"scheduler.job.{job.name}.error")
    
    def list_jobs(self) -> List[Dict]:
        return [
            {
                "name": job.name,
                "interval": job.interval,
                "next_run": job.next_run
            }
            for job in self._jobs.values()
        ]
