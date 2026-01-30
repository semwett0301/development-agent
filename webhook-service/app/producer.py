from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from aiokafka import AIOKafkaProducer

from .config import settings


class _ProducerState:
    instance: AIOKafkaProducer | None = None


_state = _ProducerState()


@asynccontextmanager
async def lifespan(_app: object) -> AsyncIterator[None]:
    _state.instance = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
    )

    await _state.instance.start()

    try:
        yield
    finally:
        await _state.instance.stop()


async def send(topic: str, key: str, value: bytes, delivery_id: str) -> None:
    assert _state.instance is not None

    await _state.instance.send(
        topic=topic,
        key=key.encode(),
        value=value,
        headers=[("x-github-delivery", delivery_id.encode())],
    )
