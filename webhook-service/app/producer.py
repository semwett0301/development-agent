from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from aiokafka import AIOKafkaProducer

from config import settings

_producer: AIOKafkaProducer | None = None


@asynccontextmanager
async def lifespan(_app: object) -> AsyncIterator[None]:
    global _producer

    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )

    await _producer.start()

    try:
        yield
    finally:
        await _producer.stop()


async def send(topic: str, key: str, value: bytes, delivery_id: str) -> None:
    assert _producer is not None

    await _producer.send(
        topic=topic,
        key=key.encode(),
        value=value,
        headers=[("x-github-delivery", delivery_id.encode())],
    )