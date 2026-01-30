import asyncio
import logging
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

from .config import settings
from .agent import run_agent
from shared.kafka.events import CodingEvent
from shared.kafka.topics import CODING_EVENTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def consume_events(consumer: AIOKafkaConsumer):
    """Consume events from Kafka and process them."""
    while True:
        try:
            async for msg in consumer:
                try:
                    event = CodingEvent.model_validate_json(msg.value)
                    logger.info(
                        f"Received event: type={event.type}, "
                        f"repo={event.repository}, issue=#{event.issue_number}"
                    )

                    if event.type == "START":
                        await asyncio.create_task(
                            run_agent_async(event.repository,
                                            event.issue_number)
                        )

                except Exception as e:
                    logger.error(f"Failed to process message: {e}")

        except Exception as e:
            logger.error(f"Consumer error: {e}")
            await asyncio.sleep(5)


async def run_agent_async(repo: str, issue_number: int):
    """Run the coding agent asynchronously."""
    logger.info(f"Starting agent for {repo} issue #{issue_number}")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_agent(repo=repo, issue_number=issue_number,
                              langfuse_trace_id=f"{repo}/{issue_number}")
        )

        if result.success:
            logger.info(f"Agent completed successfully: PR {
                result.pull_request.url}")
        else:
            logger.error(f"Agent failed: {result.error}")

    except Exception as e:
        logger.exception(f"Agent execution failed: {e}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    consumer = AIOKafkaConsumer(
        CODING_EVENTS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="coding-agent",
        auto_offset_reset="earliest",
    )

    await consumer.start()
    logger.info(f"Kafka consumer started, listening to {CODING_EVENTS}")

    task = asyncio.create_task(consume_events(consumer))

    yield

    task.cancel()
    await consumer.stop()
    logger.info("Kafka consumer stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
