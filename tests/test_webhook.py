import hmac
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


WEBHOOK_SECRET = "test-secret"


def make_signature(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def test_webhook_valid_signature(client, mocker):
    """Valid signature → 200 OK"""
    mocker.patch("app.webhooks.router._queue.push_event", new_callable=AsyncMock)
    mocker.patch("app.db.session.AsyncSessionLocal")

    payload = {
        "action": "opened",
        "issue": {"number": 1, "title": "Test"},
        "repository": {"full_name": "owner/repo"},
    }
    body = json.dumps(payload).encode()
    sig = make_signature(body, WEBHOOK_SECRET)

    response = client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "issues",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200


def test_webhook_invalid_signature(client):
    """Invalid signature → 401"""
    body = b'{"action": "opened"}'
    response = client.post(
        "/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=invalid",
            "X-GitHub-Event": "issues",
        },
    )
    assert response.status_code == 401


def test_health_endpoint(client, mocker):
    """Health endpoint returns expected structure."""
    # Patch DB session
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mocker.patch("app.webhooks.router.AsyncSessionLocal", return_value=mock_cm)

    # Patch Redis ping
    mocker.patch("app.webhooks.router._queue.ping", new_callable=AsyncMock, return_value=True)

    # Patch ChromaDB HTTP call
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_resp)
    mocker.patch("httpx.AsyncClient", return_value=mock_http_client)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
