import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.logging import CorrelationIdMiddleware, get_logger
from app.core.queue import QueueWorker, RedisQueue
from app.db.session import create_all_tables, dispose_engine
from app.webhooks.router import get_queue, router as webhook_router
from app.dashboard.router import router as dashboard_router

logger = get_logger(__name__)


async def _dispatch_event(event: dict) -> None:
    """Dispatch a queued webhook event through the agent orchestrator.

    This is the glue between the Redis queue and the LangGraph orchestrator.
    Initialized at startup once all dependencies are ready.
    """
    if settings.testing:
        logger.info("TESTING mode — skipping real orchestrator dispatch", extra={"event_type": event.get("event_type")})
        return

    # Import here to avoid circular imports and allow lazy initialization
    from app.agents.orchestrator import RepoGatorOrchestrator
    from app.agents.requirements_agent import RequirementsAgent
    from app.agents.code_review_agent import CodeReviewAgent
    from app.agents.docs_agent import DocsAgent
    from app.github.client import GitHubClient
    from app.rag.knowledge_base import KnowledgeBase
    from app.db.session import AsyncSessionLocal

    kb = KnowledgeBase(
        host=settings.chromadb_host,
        port=settings.chromadb_port,
        openai_api_key=settings.openai_api_key,
        embedding_model=settings.openai_embedding_model,
    )
    github_client = GitHubClient(token=settings.github_token)
    requirements_agent = RequirementsAgent(knowledge_base=kb)
    code_review_agent = CodeReviewAgent(github_client=github_client)
    docs_agent = DocsAgent(knowledge_base=kb)

    orchestrator = RepoGatorOrchestrator(
        requirements_agent=requirements_agent,
        code_review_agent=code_review_agent,
        docs_agent=docs_agent,
        github_client=github_client,
        db_session_factory=AsyncSessionLocal,
    )

    await orchestrator.process_event(
        event_type=event["event_type"],
        payload=event["payload"],
        correlation_id=event["correlation_id"],
        repo_full_name=event["repo_full_name"],
    )


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

    # Start the queue worker as a background task
    worker = QueueWorker(queue=queue, dispatch=_dispatch_event)
    worker_task = asyncio.create_task(worker.start(), name="queue-worker")
    logger.info("Queue worker started")

    yield

    # Graceful shutdown
    worker.stop()
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

# Inject correlation ID on every request
app.add_middleware(CorrelationIdMiddleware)

# Routers
app.include_router(webhook_router, prefix="", tags=["webhooks"])
app.include_router(dashboard_router, prefix="", tags=["dashboard"])
