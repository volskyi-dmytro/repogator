import asyncio
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update as sa_update, delete as sa_delete

from app.config import settings
from app.core.logging import CorrelationIdMiddleware, get_logger
from app.core.metrics import agent_runs_total, agent_duration_seconds
from app.core.queue import QueueWorker, RedisQueue
from app.db.session import create_all_tables, dispose_engine, AsyncSessionLocal
from app.db.models import WebhookEvent, AuditLog
from app.webhooks.router import get_queue, router as webhook_router
from app.dashboard.router import router as dashboard_router
from app.auth.router import router as auth_router
from app.repos.router import router as repos_router
from app.settings_page.router import router as settings_router
from app.knowledge.router import router as knowledge_router
from app.admin.router import router as admin_router
from app.privacy.router import router as privacy_router

logger = get_logger(__name__)


async def _dispatch_event(event: dict) -> None:
    """Dispatch a queued webhook event through the agent orchestrator.

    This is the glue between the Redis queue and the LangGraph orchestrator.
    Initialized at startup once all dependencies are ready.
    """
    event_id = event.get("event_id")
    correlation_id = event.get("correlation_id", "unknown")

    if settings.testing:
        logger.info("TESTING mode — skipping real orchestrator dispatch", extra={"event_type": event.get("event_type")})
        return

    start = time.time()
    try:
        # Import here to avoid circular imports and allow lazy initialization
        from app.agents.orchestrator import RepoGatorOrchestrator
        from app.agents.requirements_agent import RequirementsAgent
        from app.agents.code_review_agent import CodeReviewAgent
        from app.agents.docs_agent import DocsAgent
        from app.github.client import GitHubClient
        from app.rag.knowledge_base import KnowledgeBase

        # Extract optional per-user keys (from per-repo webhook)
        user_openrouter_key = event.get("user_openrouter_key")
        user_openai_key = event.get("user_openai_key")
        user_openrouter_model = event.get("user_openrouter_model")
        user_openai_embedding_model = event.get("user_openai_embedding_model")
        user_is_admin = event.get("user_is_admin", False)

        # Resolve API keys — admin can fall back to system keys, others cannot
        openrouter_api_key = user_openrouter_key or (settings.openrouter_api_key if user_is_admin else None)
        openai_api_key = user_openai_key or (settings.openai_api_key if user_is_admin else None)

        if not openrouter_api_key:
            raise ValueError("No OpenRouter API key configured. Please add your API key in Settings.")
        if not openai_api_key:
            raise ValueError("No OpenAI API key configured. Please add your API key in Settings.")

        kb = KnowledgeBase(
            host=settings.chromadb_host,
            port=settings.chromadb_port,
            openai_api_key=openai_api_key,
            embedding_model=user_openai_embedding_model or settings.openai_embedding_model,
            user_id=event.get("user_id"),
        )
        github_client = GitHubClient(token=settings.github_token)
        requirements_agent = RequirementsAgent(
            knowledge_base=kb,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=user_openrouter_model,
        )
        code_review_agent = CodeReviewAgent(
            github_client=github_client,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=user_openrouter_model,
        )
        docs_agent = DocsAgent(
            knowledge_base=kb,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=user_openrouter_model,
        )

        orchestrator = RepoGatorOrchestrator(
            requirements_agent=requirements_agent,
            code_review_agent=code_review_agent,
            docs_agent=docs_agent,
            github_client=github_client,
            db_session_factory=AsyncSessionLocal,
        )

        result = await orchestrator.process_event(
            event_type=event["event_type"],
            payload=event["payload"],
            correlation_id=correlation_id,
            repo_full_name=event["repo_full_name"],
            webhook_event_id=event_id or "",
        )

        final_status = "failed" if result.get("error") else "completed"
        agent_runs_total.labels(agent_name=event.get("event_type", "unknown"), status=final_status).inc()
        logger.info(
            "Event dispatched successfully",
            extra={"correlation_id": correlation_id, "status": final_status},
        )

    except Exception as exc:
        final_status = "failed"
        agent_runs_total.labels(agent_name=event.get("event_type", "unknown"), status=final_status).inc()
        logger.error(
            "Unhandled exception in _dispatch_event",
            extra={"correlation_id": correlation_id, "error": str(exc), "traceback": traceback.format_exc()},
            exc_info=True,
        )
    finally:
        agent_duration_seconds.labels(agent_name=event.get("event_type", "unknown")).observe(time.time() - start)

    # Update WebhookEvent status in DB
    if event_id:
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    sa_update(WebhookEvent)
                    .where(WebhookEvent.id == event_id)
                    .values(status=final_status)
                )
                await session.commit()
            logger.info(
                "WebhookEvent status updated",
                extra={"event_id": event_id, "status": final_status},
            )
        except Exception as db_exc:
            logger.error(
                "Failed to update WebhookEvent status",
                extra={"event_id": event_id, "error": str(db_exc)},
                exc_info=True,
            )


async def _run_retention_cleanup() -> None:
    """Background task: delete old processed webhook events and audit log entries once per day.

    Only deletes records older than DATA_RETENTION_DAYS. Never deletes events with
    status 'received' or 'processing' — those may still be in the queue.
    """
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # run daily
            cutoff = datetime.utcnow() - timedelta(days=settings.data_retention_days)

            async with AsyncSessionLocal() as session:
                # Delete completed/failed webhook events beyond retention window
                result = await session.execute(
                    sa_delete(WebhookEvent).where(
                        WebhookEvent.created_at < cutoff,
                        WebhookEvent.status.in_(["completed", "failed"]),
                    )
                )
                events_deleted = result.rowcount

                # Delete audit log entries beyond retention window
                result = await session.execute(
                    sa_delete(AuditLog).where(AuditLog.created_at < cutoff)
                )
                audit_deleted = result.rowcount

                # Write a summary entry to the audit log
                session.add(AuditLog(
                    id=str(uuid.uuid4()),
                    correlation_id="retention-cleanup",
                    level="INFO",
                    message=(
                        f"Data retention cleanup: deleted {events_deleted} webhook events "
                        f"and {audit_deleted} audit log entries older than "
                        f"{settings.data_retention_days} days"
                    ),
                    context={
                        "events_deleted": events_deleted,
                        "audit_deleted": audit_deleted,
                        "retention_days": settings.data_retention_days,
                        "cutoff": cutoff.isoformat(),
                    },
                ))
                await session.commit()

            logger.info(
                "Retention cleanup complete",
                extra={
                    "events_deleted": events_deleted,
                    "audit_deleted": audit_deleted,
                    "retention_days": settings.data_retention_days,
                },
            )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("Retention cleanup failed", extra={"error": str(exc)}, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle.

    On startup: create DB tables, connect Redis queue, start queue worker.
    On shutdown: stop worker, disconnect Redis, dispose DB engine.
    """
    logger.info("RepoGator starting up")

    await create_all_tables()
    logger.info("Database tables verified")

    queue = get_queue()
    await queue.connect()
    logger.info("Redis queue connected")

    # Re-queue any events that were received but not processed (e.g. from a previous container restart)
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(WebhookEvent).where(WebhookEvent.status == "received")
            )
            stuck_events = result.scalars().all()
        if stuck_events:
            logger.warning(
                "Re-queuing stuck events from previous run",
                extra={"count": len(stuck_events)},
            )
            for ev in stuck_events:
                await queue.push_event({
                    "event_id": str(ev.id),
                    "correlation_id": ev.correlation_id,
                    "event_type": ev.event_type,
                    "action": ev.action,
                    "repo_full_name": ev.repo_full_name,
                    "payload": ev.payload,
                })
            logger.info("Stuck events re-queued", extra={"count": len(stuck_events)})
    except Exception as exc:
        logger.error("Failed to re-queue stuck events", extra={"error": str(exc)}, exc_info=True)

    # Start the queue worker as a background task
    worker = QueueWorker(queue=queue, dispatch=_dispatch_event)
    worker_task = asyncio.create_task(worker.start(), name="queue-worker")
    logger.info("Queue worker started")

    # Start daily data retention cleanup task
    retention_task = asyncio.create_task(_run_retention_cleanup(), name="retention-cleanup")
    logger.info("Data retention cleanup task started (runs every 24h)")

    yield

    # Graceful shutdown
    worker.stop()
    retention_task.cancel()
    try:
        await asyncio.wait_for(worker_task, timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning("Queue worker did not stop within 5s, cancelling")
        worker_task.cancel()

    await queue.disconnect()
    logger.info("Redis queue disconnected")

    await dispose_engine()
    logger.info("Database engine disposed")

    logger.info("RepoGator shut down cleanly")


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signed session cookies (itsdangerous-based, used by auth/session.py)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)

# Inject correlation ID on every request
app.add_middleware(CorrelationIdMiddleware)

# Routers
app.include_router(webhook_router, prefix="", tags=["webhooks"])
app.include_router(dashboard_router, prefix="", tags=["dashboard"])
app.include_router(auth_router, prefix="", tags=["auth"])
app.include_router(repos_router, prefix="", tags=["repos"])
app.include_router(settings_router, prefix="", tags=["settings"])
app.include_router(knowledge_router, prefix="", tags=["knowledge"])
app.include_router(admin_router, prefix="", tags=["admin"])
app.include_router(privacy_router, prefix="", tags=["privacy"])

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus metrics endpoint — internal only."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt() -> PlainTextResponse:
    content = (
        "User-agent: *\n"
        "Disallow: /dashboard\n"
        "Disallow: /repos\n"
        "Disallow: /knowledge\n"
        "Disallow: /settings\n"
    )
    return PlainTextResponse(content)
