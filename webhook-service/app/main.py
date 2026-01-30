import json

from fastapi import FastAPI, Header, Request, HTTPException

from shared.kafka.topics import CODING_EVENTS, REVIEW_EVENTS
from shared.kafka.events import CodingEvent, ReviewEvent

from .config import settings
from .producer import lifespan, send
from .verification import verify_signature

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
    action = payload.get("action")

    # Issue opened → start coding agent
    if x_github_event == "issues" and action == "opened":
        event = CodingEvent(
            type="START",
            repository=payload["repository"]["full_name"],
            issue_number=payload["issue"]["number"],
        )
        await send(
            topic=CODING_EVENTS,
            key=x_github_event,
            value=event.model_dump_json().encode(),
            delivery_id=x_github_delivery,
        )

    # Incoming REDO event (e.g. custom webhook or integration)
    elif x_github_event == "REDO":
        repo = payload["repository"]["full_name"]
        issue_number = payload.get("issue_number") or payload.get(
            "issue", {}).get("number")
        pr = payload.get("pull_request", {})
        pr_number = payload.get("pull_request_number") or (
            pr.get("number") if isinstance(pr, dict) else None)
        if issue_number is None:
            raise HTTPException(
                status_code=400, detail="REDO event must contain issue_number or issue.number")
        event = CodingEvent(
            type="REDO",
            repository=repo,
            issue_number=issue_number,
            pull_request_number=pr_number,
        )
        await send(
            topic=CODING_EVENTS,
            key=x_github_event,
            value=event.model_dump_json().encode(),
            delivery_id=x_github_delivery,
        )

    # PR review comment → redo coding agent
    elif x_github_event == "pull_request_review_comment":
        pr = payload.get("pull_request", {})
        # Get issue number from PR body (Closes #N) or use PR number
        issue_number = _extract_issue_number(
            pr.get("body", "")) or pr.get("number")
        event = CodingEvent(
            type="REDO",
            repository=payload["repository"]["full_name"],
            issue_number=issue_number,
            pull_request_number=pr.get("number"),
        )
        await send(
            topic=CODING_EVENTS,
            key=x_github_event,
            value=event.model_dump_json().encode(),
            delivery_id=x_github_delivery,
        )

    # Check suite completed → trigger review
    elif x_github_event == "check_suite" and action == "completed":
        # Get PRs associated with this check suite
        pull_requests = payload.get("check_suite", {}).get("pull_requests", [])
        for pr in pull_requests:
            event = ReviewEvent(
                repository=payload["repository"]["full_name"],
                pull_request_number=pr.get("number"),
            )
            await send(
                topic=REVIEW_EVENTS,
                key=x_github_event,
                value=event.model_dump_json().encode(),
                delivery_id=x_github_delivery,
            )

    return {"event": x_github_event, "delivery": x_github_delivery}


def _extract_issue_number(body: str) -> int | None:
    """Extract issue number from PR body (Closes #N, Fixes #N, etc.)."""
    import re
    if not body:
        return None
    match = re.search(r"(?:closes|fixes|resolves)\s+#(\d+)",
                      body, re.IGNORECASE)
    return int(match.group(1)) if match else None
