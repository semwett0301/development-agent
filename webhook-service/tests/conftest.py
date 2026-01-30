import os
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

_ROOT_PATH = str(Path(__file__).resolve().parents[2])
_SERVICE_PATH = str(Path(__file__).resolve().parents[1])
for p in (_ROOT_PATH, _SERVICE_PATH):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ["GITHUB_WEBHOOK_SECRET"] = "test_secret"
os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "localhost:9092"


@asynccontextmanager
async def _noop_lifespan(_app: object) -> AsyncIterator[None]:
    yield


@pytest.fixture(autouse=True)
def _no_kafka():
    from app.main import app

    original = app.router.lifespan_context
    app.router.lifespan_context = _noop_lifespan
    yield
    app.router.lifespan_context = original


@pytest.fixture()
def mock_send():
    with patch("app.main.send", new_callable=AsyncMock) as mock:
        yield mock
