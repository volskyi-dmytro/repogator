import hmac, hashlib, json
import pytest

WEBHOOK_SECRET = "test-secret"

def make_signature(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"

def test_webhook_valid_signature(client, mocker):
    """Valid signature → 200 OK"""
    mocker.patch("app.db.session.get_db")  # skip DB
    mocker.patch("app.core.queue.RedisQueue.push_event")  # skip Redis

    payload = {"action": "opened", "issue": {"number": 1, "title": "Test"}, "repository": {"full_name": "owner/repo"}}
    body = json.dumps(payload).encode()
    sig = make_signature(body, WEBHOOK_SECRET)

    response = client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "issues",
        "Content-Type": "application/json"
    })
    assert response.status_code == 200

def test_webhook_invalid_signature(client):
    """Invalid signature → 401"""
    body = b'{"action": "opened"}'
    response = client.post("/webhook", content=body, headers={
        "X-Hub-Signature-256": "sha256=invalid",
        "X-GitHub-Event": "issues",
    })
    assert response.status_code == 401

def test_health_endpoint(client, mocker):
    """Health endpoint returns expected structure"""
    mocker.patch("app.webhooks.router.check_db_health", return_value=True)
    mocker.patch("app.webhooks.router.check_redis_health", return_value=True)
    mocker.patch("app.webhooks.router.check_chromadb_health", return_value=True)

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
