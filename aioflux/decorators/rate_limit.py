from functools import wraps
from typing import Optional, Callable, Any
from aioflux.limiters.base import BaseLimiter
from aioflux.limiters.token_bucket import TokenBucketLimiter
from aioflux.core.storage.base import Storage
import asyncio


def rate_limit(
    rate: Optional[float] = None,
    per: float = 1.0,
    burst: Optional[float] = None,
    strategy: str = "token_bucket",
    storage: Optional[Storage] = None,
    scope: str = "default",
    key_fn: Optional[Callable[..., str]] = None,
    limiter: Optional[BaseLimiter] = None
):
    if limiter is None:
        if strategy == "token_bucket":
            limiter = TokenBucketLimiter(rate, per, burst, storage, scope)
        else:
            limiter = TokenBucketLimiter(rate, per, burst, storage, scope)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{func.__module__}.{func.__name__}"
            
            acquired = False
            while not acquired:
                acquired = await limiter.acquire(key)
                if not acquired:
                    await asyncio.sleep(0.01)
            
            return await func(*args, **kwargs)
        
        wrapper.__limiter__ = limiter
        return wrapper
    
    return decorator


def rate_limit_sync(
    rate: Optional[float] = None,
    per: float = 1.0,
    burst: Optional[float] = None,
    strategy: str = "token_bucket",
    storage: Optional[Storage] = None,
    scope: str = "default",
    key_fn: Optional[Callable[..., str]] = None,
    limiter: Optional[BaseLimiter] = None
):
    if limiter is None:
        if strategy == "token_bucket":
            limiter = TokenBucketLimiter(rate, per, burst, storage, scope)
        else:
            limiter = TokenBucketLimiter(rate, per, burst, storage, scope)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            if key_fn:
                key = key_fn(*args, **kwargs)
            else:
                key = f"{func.__module__}.{func.__name__}"
            
            loop = asyncio.get_event_loop()
            while not loop.run_until_complete(limiter.acquire(key)):
                import time
                time.sleep(0.01)
            
            try:
                return func(*args, **kwargs)
            except Exception as e:
                loop.run_until_complete(limiter.release(key))
                raise
        
        wrapper.__limiter__ = limiter
        return wrapper
    
    return decorator
