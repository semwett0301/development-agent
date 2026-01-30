import json

from fastapi import FastAPI, Header, Request, HTTPException

from shared.kafka.topics import CODING_EVENTS, INDEX_EVENTS
from shared.kafka.events import CodingEvent

from config import settings
from producer import lifespan, send
from verification import verify_signature

app = FastAPI(lifespan=lifespan)


@app.post("/github/webhook/")
async def handle_webhook(
    request: Request,
    x_github_event: str = Header(),
    x_hub_signature_256: str = Header(),
    x_github_delivery: str = Header(),
) -> dict:
    body = await request.body()

    if not verify_signature(body, settings.github_webhook_secret, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = json.loads(body)

    if x_github_event == "issues" and payload.get("action") == "opened":
        event = CodingEvent(
            body=payload["issue"]["body"],
        )

        await send(
            topic=CODING_EVENTS,
            key=x_github_event,
            value=event.model_dump_json().encode(),
            delivery_id=x_github_delivery,
        )

    elif x_github_event == "push" and payload.get("ref") == "refs/heads/main":
        await send(
            topic=INDEX_EVENTS,
            key=x_github_event,
            value=b"",
            delivery_id=x_github_delivery,
        )

    return {"event": x_github_event, "delivery": x_github_delivery}
