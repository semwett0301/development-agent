import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient, ASGITransport

from main import app

SECRET = "test_secret"


def _sign(payload: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()


def _headers(event: str, payload: bytes, delivery: str = "test-delivery-id") -> dict:
    return {
        "x-github-event": event,
        "x-hub-signature-256": _sign(payload),
        "x-github-delivery": delivery,
    }


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_issue_created_sends_to_coding_events(client, mock_send):
    payload = json.dumps({
        "action": "opened",
        "issue": {"body": "Fix the bug"},
    }).encode()

    response = await client.post("/github/webhook", content=payload, headers=_headers("issues", payload))

    assert response.status_code == 200
    assert response.json() == {"event": "issues",
                               "delivery": "test-delivery-id"}

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "coding-events"
    assert call_kwargs["key"] == "issues"

    value = json.loads(call_kwargs["value"])
    assert value["body"] == "Fix the bug"


async def test_push_to_main_sends_to_index_events(client, mock_send):
    payload = json.dumps({"ref": "refs/heads/main"}).encode()

    response = await client.post("/github/webhook", content=payload, headers=_headers("push", payload))

    assert response.status_code == 200

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "index-events"
    assert call_kwargs["value"] == b""


async def test_push_to_non_main_does_not_send(client, mock_send):
    payload = json.dumps({"ref": "refs/heads/feature"}).encode()

    response = await client.post("/github/webhook", content=payload, headers=_headers("push", payload))

    assert response.status_code == 200
    mock_send.assert_not_called()


async def test_unhandled_event_does_not_send(client, mock_send):
    payload = json.dumps({"action": "completed"}).encode()

    response = await client.post("/github/webhook", content=payload, headers=_headers("check_run", payload))

    assert response.status_code == 200
    mock_send.assert_not_called()


async def test_invalid_signature_returns_403(client, mock_send):
    payload = json.dumps({"action": "opened"}).encode()
    headers = {
        "x-github-event": "issues",
        "x-hub-signature-256": "sha256=invalid",
        "x-github-delivery": "test-delivery-id",
    }

    response = await client.post("/github/webhook", content=payload, headers=headers)

    assert response.status_code == 403
    mock_send.assert_not_called()


async def test_issue_with_null_body(client, mock_send):
    payload = json.dumps({
        "action": "opened",
        "issue": {"body": None},
    }).encode()

    response = await client.post("/github/webhook", content=payload, headers=_headers("issues", payload))

    assert response.status_code == 200
    mock_send.assert_called_once()

    value = json.loads(mock_send.call_args.kwargs["value"])
    assert value["body"] is None
