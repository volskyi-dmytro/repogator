import pytest
import os
os.environ["TESTING"] = "true"

# Set all required env vars for testing
os.environ.setdefault("GITHUB_TOKEN", "test-token")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("GITHUB_REPO", "test-owner/test-repo")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from fastapi.testclient import TestClient
import pytest_asyncio

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)
