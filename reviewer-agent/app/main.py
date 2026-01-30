"""
Reviewer Agent - Kafka consumer and FastAPI application.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer
from fastapi import FastAPI

from .config import settings, load_config
from .services import ReviewService
from .clients import flush_langfuse
from shared.kafka.events import ReviewEvent
from shared.kafka.topics import REVIEW_EVENTS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _observe_if_available(fn):
    """Wrap in Langfuse @observe when available."""
    try:
        from langfuse import observe
        return observe(name="reviewer_agent_run")(fn)
    except ImportError:
        return fn


@_observe_if_available
def run_review(repo: str, pr_number: int) -> dict:
    """Run the reviewer agent on a pull request."""
    config = load_config()
    service = ReviewService(config)

    # Parse owner/repo from repository string
    owner, repo_name = repo.split("/")
    result = service.review_pr(owner, repo_name, pr_number)

    if config.langfuse and config.langfuse.is_configured:
        flush_langfuse()

    return {
        "success": True,
        "is_normal": result.is_normal,
        "requirements_met": result.requirements_met,
        "ci_passed": result.ci_passed,
        "summary_similarity": result.summary_similarity,
        "errors_count": len(result.errors),
    }


async def run_review_async(repo: str, pr_number: int):
    """Run the reviewer agent asynchronously."""
    logger.info("[review] Starting review for %s PR #%s", repo, pr_number)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_review(repo=repo, pr_number=pr_number)
        )

        if result["is_normal"]:
            logger.info(
                "[review] Completed: PR is normal (requirements_met=%s, ci_passed=%s)",
                result["requirements_met"],
                result["ci_passed"],
            )
        else:
            logger.warning(
                "[review] Completed: PR has issues (errors_count=%s)",
                result["errors_count"],
            )

    except Exception as e:
        logger.exception("[review] Review execution failed: %s", e)


async def consume_events(consumer: AIOKafkaConsumer):
    """Consume events from Kafka and process them."""
    while True:
        try:
            async for msg in consumer:
                try:
                    event = ReviewEvent.model_validate_json(msg.value)
                    logger.info(
                        "[review] Received event: repo=%s, pr=#%s",
                        event.repository,
                        event.pull_request_number,
                    )
                    asyncio.create_task(
                        run_review_async(
                            event.repository,
                            event.pull_request_number
                        )
                    )

                except Exception as e:
                    logger.error("[review] Failed to process message: %s", e)

        except Exception as e:
            logger.error("[review] Consumer error: %s", e)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    consumer = AIOKafkaConsumer(
        REVIEW_EVENTS,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="reviewer-agent",
        auto_offset_reset="earliest",
    )

    await consumer.start()
    logger.info(
        "[review] Kafka consumer started, listening to %s", REVIEW_EVENTS)

    task = asyncio.create_task(consume_events(consumer))

    yield

    task.cancel()
    await consumer.stop()
    logger.info("[review] Kafka consumer stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
