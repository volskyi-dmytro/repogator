import pytest
import os

os.environ["TESTING"] = "true"
os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("GITHUB_REPO", "test-owner/test-repo")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key-for-testing-only")
os.environ.setdefault("APP_BASE_URL", "http://localhost:8000")

from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with (
        patch("app.db.session.create_all_tables", new_callable=AsyncMock),
        patch("app.core.queue.RedisQueue.connect", new_callable=AsyncMock),
        patch("app.core.queue.RedisQueue.disconnect", new_callable=AsyncMock),
        patch("app.core.queue.RedisQueue.pop_event", new_callable=AsyncMock, return_value=None),
    ):
        from app.main import app
        yield TestClient(app)
