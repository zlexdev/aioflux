import asyncio
from dataclasses import dataclass
from typing import List

from aioflux import BatchFlux, FluxConfig, LimiterFactory, QueueFactory


@dataclass
class DBRecord:
    """Запись для записи в БД."""
    id: int
    data: str


async def batch_insert_to_db(records: List[DBRecord]) -> List[int]:
    """Батч-вставка в БД. Эмулируем SQL bulk insert."""
    await asyncio.sleep(0.1)
    print(f"Inserted {len(records)} records to DB")
    return [r.id for r in records]


async def batch_api_request(items: List[dict]) -> List[dict]:
    """Батч-запрос к внешнему API."""
    await asyncio.sleep(0.2)
    print(f"Sent {len(items)} items to API")
    return [{"id": i["id"], "status": "ok"} for i in items]

# todo фикс статы в 1,4,5

async def example_1_basic_batch_flux():
    """Базовый пример BatchFlux для оптимизации записи в БД."""
    print("\n=== Example 1: Basic BatchFlux ===\n")

    queue = QueueFactory.fifo()

    config = FluxConfig(
        workers=3,
        max_retries=2,
        timeout=5.0
    )

    flux = BatchFlux(
        queue=queue,
        handler=batch_insert_to_db,
        config=config,
        name="db_insert",
        batch_size=50,
        batch_timeout=1.0,
        max_concurrent=5
    )

    await flux.start()

    for i in range(200):
        record = DBRecord(id=i, data=f"data_{i}")
        await flux.submit(record)

    await flux.wait_complete(timeout=10.0)

    print(f"Stats: {flux.stats()}")

    await flux.stop()


async def example_2_batch_with_rate_limit():
    """BatchFlux с rate limiting. Ограничиваем нагрузку на БД."""
    print("\n=== Example 2: BatchFlux with Rate Limit ===\n")

    queue = QueueFactory.fifo()
    limiter = LimiterFactory.token_bucket(rate=100, per=1)

    flux = BatchFlux(
        queue=queue,
        handler=batch_insert_to_db,
        limiter=limiter,
        name="limited_insert",
        batch_size=25,
        batch_timeout=0.5
    )

    await flux.start()

    for i in range(150):
        await flux.submit(DBRecord(id=i, data=f"data_{i}"))

    await flux.wait_complete(timeout=10.0)

    print(f"Stats: {flux.stats()}")

    await flux.stop()


async def example_3_batch_process_method():
    """Использование batch_process для bulk обработки списка."""
    print("\n=== Example 3: batch_process Method ===\n")

    queue = QueueFactory.fifo()

    flux = BatchFlux[DBRecord, list[int]](
        queue=queue,
        handler=batch_insert_to_db,
        name="batch_processor",
        batch_size=30,
        max_concurrent=3
    )

    records = [DBRecord(id=i, data=f"data_{i}") for i in range(1000)]

    async def process_batch(batch: List[DBRecord]) -> List[int]:
        return await batch_insert_to_db(batch)

    results = await flux.batch_process(
        items=records,
        func=process_batch,
        batch_size=50,
        max_concurrent=5
    )

    print(f"Processed {len(results)} batches")
    print(results)
    print(f"Total records: {sum(len(r) for r in results)}")


async def example_4_batch_gather():
    """batch_gather для параллельного выполнения разных функций батчами."""
    print("\n=== Example 4: batch_gather ===\n")

    from functools import partial

    queue = QueueFactory.fifo()

    flux = BatchFlux(
        queue=queue,
        handler=batch_api_request,
        name="batch_gather",
        batch_size=5
    )

    async def fetch_user(uid: int) -> dict:
        await asyncio.sleep(0.05)
        return {"user_id": uid, "name": f"User {uid}"}

    async def fetch_order(oid: int) -> dict:
        await asyncio.sleep(0.05)
        return {"order_id": oid, "total": oid * 100}

    async def fetch_product(pid: int) -> dict:
        await asyncio.sleep(0.05)
        return {"product_id": pid, "price": pid * 10}

    funcs = []
    for i in range(100):
        funcs.append(partial(fetch_user, i))
        funcs.append(partial(fetch_order, i))
        funcs.append(partial(fetch_product, i))

    results = await flux.batch_gather(*funcs, batch_size=20)

    print(f"Gathered {len(results)} results")
    print(f"Sample results: {results[:5]}")


async def example_5_real_world_etl():
    """Реальный пример ETL: читаем файл, трансформируем, пишем в БД батчами."""
    print("\n=== Example 5: Real-world ETL ===\n")

    async def transform_records(records: List[dict]) -> List[DBRecord]:
        """Трансформация данных."""
        return [
            DBRecord(
                id=r["id"],
                data=r["raw_data"].upper()
            )
            for r in records
        ]

    async def load_to_db(records: List[DBRecord]) -> List[int]:
        """Загрузка в БД."""
        await asyncio.sleep(0.1)
        return [r.id for r in records]

    queue = QueueFactory.fifo()
    limiter = LimiterFactory.token_bucket(rate=500, per=1)

    flux = BatchFlux(
        queue=queue,
        handler=load_to_db,
        limiter=limiter,
        name="etl_pipeline",
        batch_size=100,
        batch_timeout=0.5,
        max_concurrent=3
    )

    await flux.start()

    raw_data = [
        {"id": i, "raw_data": f"raw_value_{i}"}
        for i in range(5000)
    ]

    for chunk_start in range(0, len(raw_data), 200):
        chunk = raw_data[chunk_start:chunk_start + 200]
        transformed = await transform_records(chunk)

        for record in transformed:
            await flux.submit(record)

    await flux.wait_complete(timeout=15.0)

    print(f"ETL Stats: {flux.stats()}")

    await flux.stop()


async def example_6_multi_source_aggregation():
    """Агрегация данных из нескольких источников батчами."""
    print("\n=== Example 6: Multi-source Aggregation ===\n")

    async def fetch_from_api_a(ids: List[int]) -> List[dict]:
        await asyncio.sleep(0.15)
        return [{"id": i, "source": "A", "value": i * 2} for i in ids]

    async def fetch_from_api_b(ids: List[int]) -> List[dict]:
        await asyncio.sleep(0.15)
        return [{"id": i, "source": "B", "value": i * 3} for i in ids]

    async def fetch_from_api_c(ids: List[int]) -> List[dict]:
        await asyncio.sleep(0.15)
        return [{"id": i, "source": "C", "value": i * 5} for i in ids]

    queue = QueueFactory.fifo()

    flux = BatchFlux[int, list[dict]](
        queue=queue,
        handler=fetch_from_api_a,
        name="aggregator",
        batch_size=20,
        max_concurrent=10
    )

    ids = list(range(500))

    results_a = await flux.batch_process(ids, fetch_from_api_a, batch_size=25, max_concurrent=5)
    results_b = await flux.batch_process(ids, fetch_from_api_b, batch_size=25, max_concurrent=5)
    results_c = await flux.batch_process(ids, fetch_from_api_c, batch_size=25, max_concurrent=5)

    all_results = []
    for batch_a, batch_b, batch_c in zip(results_a, results_b, results_c):
        all_results.extend(batch_a)
        all_results.extend(batch_b)
        all_results.extend(batch_c)

    print(f"Aggregated {len(all_results)} records from 3 sources")
    print(f"Sample: {all_results[:6]}")


async def main():
    """Запуск всех примеров."""

    await example_1_basic_batch_flux()
    await example_2_batch_with_rate_limit()
    await example_3_batch_process_method()
    await example_4_batch_gather()
    await example_5_real_world_etl()
    await example_6_multi_source_aggregation()

    print("\n=== All Examples Completed ===\n")


if __name__ == "__main__":
    asyncio.run(main())