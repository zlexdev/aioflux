import asyncio
import sys
sys.path.insert(0, '/home/claude')

from aioflux import LimiterFactory, QueueFactory, rate_limit, queued


async def test_token_bucket():
    print("Testing Token Bucket...")
    limiter = LimiterFactory.token_bucket(rate=5, per=1.0)
    
    accepted = 0
    rejected = 0
    
    for i in range(10):
        if await limiter.acquire("test"):
            accepted += 1
        else:
            rejected += 1
    
    print(f"Accepted: {accepted}, Rejected: {rejected}")
    assert accepted <= 5, "Rate limit not working"
    print("✓ Token Bucket test passed\n")


async def test_priority_queue():
    print("Testing Priority Queue...")
    queue = QueueFactory.priority(workers=2)
    await queue.start()
    
    results = []
    
    async def task(name, priority):
        results.append(name)
    
    await queue.put(lambda: task("low", 1), priority=1)
    await queue.put(lambda: task("high", 10), priority=10)
    await queue.put(lambda: task("medium", 5), priority=5)
    
    await asyncio.sleep(0.5)
    await queue.stop()
    
    print(f"Execution order: {results}")
    assert results[0] == "high", "Priority queue not working"
    print("✓ Priority Queue test passed\n")


async def test_rate_limit_decorator():
    print("Testing @rate_limit decorator...")
    
    call_count = [0]
    limiter = LimiterFactory.token_bucket(rate=3, per=1.0)
    
    @rate_limit(limiter=limiter)
    async def limited_func():
        call_count[0] += 1
        return "success"
    
    start = asyncio.get_event_loop().time()
    for i in range(5):
        await limited_func()
    elapsed = asyncio.get_event_loop().time() - start
    
    print(f"Successful calls: {call_count[0]}, Time: {elapsed:.2f}s")
    assert call_count[0] == 5, "All calls should succeed"
    assert elapsed > 0.5, "Should have waited for rate limit"
    print("✓ Rate limit decorator test passed\n")


async def test_fifo_batching():
    print("Testing FIFO with batching...")
    
    batches = []
    
    async def batch_processor(items):
        batches.append(len(items))
    
    queue = QueueFactory.fifo(workers=1, batch_size=3, batch_timeout=0.5, batch_fn=batch_processor)
    await queue.start()
    
    for i in range(7):
        await queue.put(f"item_{i}")
    
    await asyncio.sleep(1.5)
    await queue.stop()
    
    print(f"Batch sizes: {batches}")
    assert len(batches) > 0, "Batching not working"
    print("✓ FIFO batching test passed\n")


async def test_adaptive_limiter():
    print("Testing Adaptive Limiter...")
    
    limiter = LimiterFactory.adaptive(initial_rate=10, min_rate=5, max_rate=20)
    
    initial_stats = await limiter.get_stats("test")
    print(f"Initial rate: {initial_stats['current_rate']}")
    
    for _ in range(20):
        await limiter.acquire("test")
        await limiter.report_success()
    
    final_stats = await limiter.get_stats("test")
    print(f"Final rate: {final_stats['current_rate']}")
    
    assert final_stats['current_rate'] > initial_stats['current_rate'], "Adaptive limiter not increasing"
    print("Adaptive limiter test passed\n")


async def main():
    print("="*60)
    print("Running AioFlux Tests")
    print("="*60 + "\n")
    
    tests = [
        test_token_bucket,
        test_priority_queue,
        test_rate_limit_decorator,
        test_fifo_batching,
        test_adaptive_limiter,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"✗ Test failed: {e}\n")
            failed += 1
    
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
