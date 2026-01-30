import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app

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
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 42, "title": "Test issue", "body": "Fix the bug"},
    }).encode()

    response = await client.post("/github/webhook/", content=payload, headers=_headers("issues", payload))

    assert response.status_code == 200
    assert response.json() == {"event": "issues",
                               "delivery": "test-delivery-id"}

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "coding-events"
    assert call_kwargs["key"] == "issues"

    value = json.loads(call_kwargs["value"])
    assert value["type"] == "START"
    assert value["repository"] == "owner/repo"
    assert value["issue_number"] == 42


async def test_redo_event_sends_redo(client, mock_send):
    """Incoming webhook with x-github-event: REDO sends CodingEvent type REDO."""
    payload = json.dumps({
        "repository": {"full_name": "owner/repo"},
        "issue_number": 42,
        "pull_request_number": 100,
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("REDO", payload))

    assert response.status_code == 200
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "coding-events"
    assert call_kwargs["key"] == "REDO"

    value = json.loads(call_kwargs["value"])
    assert value["type"] == "REDO"
    assert value["repository"] == "owner/repo"
    assert value["issue_number"] == 42
    assert value["pull_request_number"] == 100


async def test_redo_event_with_issue_object(client, mock_send):
    """REDO event can use payload.issue.number instead of issue_number."""
    payload = json.dumps({
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 99},
        "pull_request": {"number": 101},
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("REDO", payload))

    assert response.status_code == 200
    value = json.loads(mock_send.call_args.kwargs["value"])
    assert value["type"] == "REDO"
    assert value["issue_number"] == 99
    assert value["pull_request_number"] == 101


async def test_redo_event_missing_issue_returns_400(client, mock_send):
    payload = json.dumps({
        "repository": {"full_name": "owner/repo"},
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("REDO", payload))

    assert response.status_code == 400
    mock_send.assert_not_called()


async def test_pr_review_comment_sends_redo(client, mock_send):
    payload = json.dumps({
        "action": "created",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {
            "number": 123,
            "body": "Closes #42",
        },
        "comment": {"body": "Please fix this"},
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("pull_request_review_comment", payload))

    assert response.status_code == 200

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "coding-events"
    assert call_kwargs["key"] == "pull_request_review_comment"

    value = json.loads(call_kwargs["value"])
    assert value["type"] == "REDO"
    assert value["repository"] == "owner/repo"
    assert value["issue_number"] == 42
    assert value["pull_request_number"] == 123


async def test_pr_review_comment_uses_pr_number_if_no_issue(client, mock_send):
    payload = json.dumps({
        "action": "created",
        "repository": {"full_name": "owner/repo"},
        "pull_request": {
            "number": 99,
            "body": "Some changes without issue link",
        },
        "comment": {"body": "Fix this"},
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("pull_request_review", payload))

    assert response.status_code == 200

    value = json.loads(mock_send.call_args.kwargs["value"])
    assert value["type"] == "REDO"
    assert value["issue_number"] == 99
    assert value["pull_request_number"] == 99


async def test_check_suite_completed_sends_to_review_events(client, mock_send):
    payload = json.dumps({
        "action": "completed",
        "repository": {"full_name": "owner/repo"},
        "check_suite": {
            "pull_requests": [{"number": 123}],
        },
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("check_suite", payload))

    assert response.status_code == 200

    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["topic"] == "review-events"
    assert call_kwargs["key"] == "check_suite"

    value = json.loads(call_kwargs["value"])
    assert value["repository"] == "owner/repo"
    assert value["pull_request_number"] == 123


async def test_check_suite_completed_no_prs_does_not_send(client, mock_send):
    payload = json.dumps({
        "action": "completed",
        "repository": {"full_name": "owner/repo"},
        "check_suite": {
            "pull_requests": [],
        },
    }).encode()

    response = await client.post(
        "/github/webhook/", content=payload,
        headers=_headers("check_suite", payload))

    assert response.status_code == 200
    mock_send.assert_not_called()


async def test_unhandled_event_does_not_send(client, mock_send):
    payload = json.dumps({"action": "completed"}).encode()

    response = await client.post("/github/webhook/", content=payload, headers=_headers("check_run", payload))

    assert response.status_code == 200
    mock_send.assert_not_called()


async def test_invalid_signature_returns_403(client, mock_send):
    payload = json.dumps({"action": "opened"}).encode()
    headers = {
        "x-github-event": "issues",
        "x-hub-signature-256": "sha256=invalid",
        "x-github-delivery": "test-delivery-id",
    }

    response = await client.post("/github/webhook/", content=payload, headers=headers)

    assert response.status_code == 403
    mock_send.assert_not_called()


async def test_issue_with_null_body(client, mock_send):
    payload = json.dumps({
        "action": "opened",
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 42, "title": "Test issue", "body": None},
    }).encode()

    response = await client.post("/github/webhook/", content=payload, headers=_headers("issues", payload))

    assert response.status_code == 200
    mock_send.assert_called_once()

    value = json.loads(mock_send.call_args.kwargs["value"])
    assert value["type"] == "START"
    assert value["repository"] == "owner/repo"
    assert value["issue_number"] == 42
