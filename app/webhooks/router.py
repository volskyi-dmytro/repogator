import hashlib
import hmac
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import text

from sqlalchemy import select as sa_select

from app.config import settings
from app.core.logging import get_logger
from app.core.queue import RedisQueue
from app.db.models import TrackedRepo, User, UserSettings, WebhookEvent
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)
router = APIRouter()

# Module-level queue instance; shared with main.py lifespan
_queue: RedisQueue = RedisQueue()


def get_queue() -> RedisQueue:
    """Return the module-level RedisQueue instance."""
    return _queue


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify the GitHub HMAC-SHA256 webhook signature.

    Uses hmac.compare_digest to prevent timing attacks.

    Args:
        raw_body: The raw request body bytes.
        signature_header: Value of the X-Hub-Signature-256 header.

    Returns:
        True if the signature matches, False otherwise.
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_sig = signature_header[len("sha256="):]
    mac = hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    )
    return hmac.compare_digest(mac.hexdigest(), expected_sig)


@router.post("/webhook/{repo_owner}/{repo_name}")
async def handle_per_repo_webhook(
    repo_owner: str,
    repo_name: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Per-repo webhook endpoint with per-repo HMAC secret."""
    raw_body = await request.body()
    repo_full_name = f"{repo_owner}/{repo_name}"

    # Look up TrackedRepo
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa_select(TrackedRepo).where(
                TrackedRepo.repo_full_name == repo_full_name,
                TrackedRepo.is_active == True,
            )
        )
        tracked = result.scalar_one_or_none()

    if not tracked:
        raise HTTPException(status_code=404, detail="Repo not tracked")

    # Verify signature with per-repo secret
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature")
    expected_sig = signature[len("sha256="):]
    mac = hmac.new(
        tracked.webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    )
    if not hmac.compare_digest(mac.hexdigest(), expected_sig):
        logger.warning("Per-repo webhook signature failed", extra={"repo": repo_full_name})
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse event
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    action = payload.get("action", "unknown")
    correlation_id = str(uuid.uuid4())

    # Load user settings for per-user API keys
    user_openrouter_key = None
    user_openai_key = None
    user_openrouter_model = None
    user_openai_embedding_model = None

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa_select(UserSettings).where(UserSettings.user_id == tracked.user_id)
        )
        user_settings = result.scalar_one_or_none()
        if user_settings:
            user_openrouter_key = user_settings.openrouter_api_key
            user_openai_key = user_settings.openai_api_key
            user_openrouter_model = user_settings.openrouter_model
            user_openai_embedding_model = user_settings.openai_embedding_model

    # Fetch user is_admin flag
    user_is_admin = False
    async with AsyncSessionLocal() as session:
        user_result = await session.execute(
            sa_select(User).where(User.id == tracked.user_id)
        )
        user_obj = user_result.scalar_one_or_none()
        if user_obj:
            user_is_admin = user_obj.is_admin

    # Persist WebhookEvent
    async with AsyncSessionLocal() as session:
        event = WebhookEvent(
            correlation_id=correlation_id,
            event_type=event_type,
            action=action,
            repo_full_name=repo_full_name,
            payload=payload,
            status="received",
            created_at=datetime.utcnow(),
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    # Push to queue with user settings
    queue_payload = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "event_type": event_type,
        "action": action,
        "repo_full_name": repo_full_name,
        "payload": payload,
        "user_openrouter_key": user_openrouter_key,
        "user_openai_key": user_openai_key,
        "user_openrouter_model": user_openrouter_model,
        "user_openai_embedding_model": user_openai_embedding_model,
        "user_is_admin": user_is_admin,
    }
    await _queue.push_event(queue_payload)

    logger.info(
        "Per-repo webhook received and enqueued",
        extra={"correlation_id": correlation_id, "repo": repo_full_name},
    )

    return {"status": "accepted", "correlation_id": correlation_id}


@router.post("/webhook")
async def handle_webhook(
    request: Request, background_tasks: BackgroundTasks
) -> dict:
    """Receive a GitHub webhook, verify it, persist it, and enqueue for processing.

    Returns 200 immediately so GitHub does not time out waiting for processing.
    """
    raw_body = await request.body()

    # 1. Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(raw_body, signature):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    # 2. Parse event type and payload
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    action = payload.get("action", "unknown")
    repo_full_name = payload.get("repository", {}).get("full_name", "unknown")

    # 3. Generate correlation ID
    correlation_id = str(uuid.uuid4())

    # 4. Persist WebhookEvent to DB
    async with AsyncSessionLocal() as session:
        event = WebhookEvent(
            correlation_id=correlation_id,
            event_type=event_type,
            action=action,
            repo_full_name=repo_full_name,
            payload=payload,
            status="received",
            created_at=datetime.utcnow(),
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    # 5. Push to Redis queue
    queue_payload = {
        "event_id": event_id,
        "correlation_id": correlation_id,
        "event_type": event_type,
        "action": action,
        "repo_full_name": repo_full_name,
        "payload": payload,
    }
    await _queue.push_event(queue_payload)

    logger.info(
        "Webhook received and enqueued",
        extra={
            "correlation_id": correlation_id,
            "event_type": event_type,
            "action": action,
        },
    )

    # 6. Return 200 immediately
    return {"status": "accepted", "correlation_id": correlation_id}


@router.get("/health")
async def health() -> dict:
    """Health check endpoint verifying DB, Redis, and ChromaDB connectivity.

    Returns:
        JSON with overall status and per-service status strings.
    """
    results: dict[str, str] = {}

    # Check DB
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        results["db"] = "ok"
    except Exception as exc:
        logger.error("DB health check failed", extra={"error": str(exc)})
        results["db"] = "error"

    # Check Redis
    try:
        ok = await _queue.ping()
        results["redis"] = "ok" if ok else "error"
    except Exception as exc:
        logger.error("Redis health check failed", extra={"error": str(exc)})
        results["redis"] = "error"

    # Check ChromaDB
    try:
        import httpx

        chromadb_url = (
            f"http://{settings.chromadb_host}:{settings.chromadb_port}/api/v1/heartbeat"
        )
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(chromadb_url)
        results["chromadb"] = "ok" if resp.status_code == 200 else "error"
    except Exception as exc:
        logger.error("ChromaDB health check failed", extra={"error": str(exc)})
        results["chromadb"] = "error"

    overall = "healthy" if all(v == "ok" for v in results.values()) else "degraded"
    return {"status": overall, "services": results}
