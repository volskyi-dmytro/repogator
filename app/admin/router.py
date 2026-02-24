import shutil

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, text

from app.auth.session import require_user
from app.config import settings
from app.db.models import User, TrackedRepo, UserSettings, WebhookEvent, AgentAction, KnowledgeDocument
from app.db.session import AsyncSessionLocal

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    session_data = require_user(request)
    if not session_data.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    stats = await _collect_admin_stats(session_data)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "stats": stats,
        "user": session_data,
        "app_name": settings.app_name,
    })


async def _collect_admin_stats(session_data: dict) -> dict:
    stats = {}

    async with AsyncSessionLocal() as session:
        stats["total_users"] = await session.scalar(
            select(func.count()).select_from(User)
        )
        stats["total_repos"] = await session.scalar(
            select(func.count()).select_from(TrackedRepo)
            .where(TrackedRepo.is_active == True)
        )
        stats["total_events"] = await session.scalar(
            select(func.count()).select_from(WebhookEvent)
        ) or 0
        stats["events_completed"] = await session.scalar(
            select(func.count()).select_from(WebhookEvent)
            .where(WebhookEvent.status == "completed")
        ) or 0
        stats["events_failed"] = await session.scalar(
            select(func.count()).select_from(WebhookEvent)
            .where(WebhookEvent.status == "failed")
        ) or 0
        stats["total_agent_runs"] = await session.scalar(
            select(func.count()).select_from(AgentAction)
        ) or 0
        stats["kb_documents"] = await session.scalar(
            select(func.count()).select_from(KnowledgeDocument)
        ) or 0
        stats["users_with_own_keys"] = await session.scalar(
            select(func.count()).select_from(UserSettings)
            .where(UserSettings.openrouter_api_key != None)
        ) or 0

        result = await session.execute(
            select(UserSettings.user_id)
            .where(UserSettings.openrouter_api_key != None)
        )
        stats["users_with_keys_set"] = {row[0] for row in result.all()}

        total = stats["total_events"]
        completed = stats["events_completed"]
        stats["success_rate"] = round(completed / total * 100, 1) if total > 0 else 0.0

        result = await session.execute(
            select(User).order_by(User.created_at.desc()).limit(10)
        )
        stats["recent_users"] = result.scalars().all()

        result = await session.execute(
            select(
                WebhookEvent.repo_full_name,
                func.count().label("event_count")
            )
            .group_by(WebhookEvent.repo_full_name)
            .order_by(func.count().desc())
            .limit(10)
        )
        stats["top_repos"] = result.all()

    # System stats via psutil
    import psutil

    disk = shutil.disk_usage("/")
    stats["disk_total_gb"] = round(disk.total / 1024**3, 1)
    stats["disk_used_gb"] = round(disk.used / 1024**3, 1)
    stats["disk_free_gb"] = round(disk.free / 1024**3, 1)
    stats["disk_percent"] = round(disk.used / disk.total * 100, 1)

    stats["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    stats["ram_total_gb"] = round(mem.total / 1024**3, 1)
    stats["ram_used_gb"] = round(mem.used / 1024**3, 1)
    stats["ram_percent"] = round(mem.percent, 1)

    # Redis queue depth
    try:
        from app.webhooks.router import get_queue
        queue = get_queue()
        stats["queue_depth"] = await queue._ensure_connected().llen(settings.webhook_queue_name)
    except Exception:
        stats["queue_depth"] = "unavailable"

    # PostgreSQL DB size
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            stats["postgres_size"] = result.scalar()
    except Exception:
        stats["postgres_size"] = "unavailable"

    # ChromaDB collections
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                f"http://{settings.chromadb_host}:{settings.chromadb_port}/api/v1/collections"
            )
            collections = resp.json()
            stats["chroma_collections"] = len(collections)
            stats["chroma_collection_list"] = [
                {"name": c["name"], "count": c.get("metadata", {}).get("count", "?")}
                for c in collections
            ]
    except Exception:
        stats["chroma_collections"] = "unavailable"
        stats["chroma_collection_list"] = []

    return stats
