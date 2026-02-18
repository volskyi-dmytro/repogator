"""Dashboard router for RepoGator monitoring UI."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from app.config import settings
from app.db.models import WebhookEvent, AgentAction
from app.db.session import AsyncSessionLocal
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main monitoring dashboard with live stats from DB."""
    stats = {
        "total_events": 0,
        "issues_enriched": 0,
        "prs_reviewed": 0,
        "docs_generated": 0,
    }
    recent_events = []

    if not settings.testing:
        try:
            async with AsyncSessionLocal() as session:
                # Total events
                total = await session.scalar(select(func.count()).select_from(WebhookEvent))
                stats["total_events"] = total or 0

                # Issues enriched (requirements agent)
                issues = await session.scalar(
                    select(func.count()).select_from(AgentAction).where(AgentAction.agent_name == "requirements_agent")
                )
                stats["issues_enriched"] = issues or 0

                # PRs reviewed
                prs = await session.scalar(
                    select(func.count()).select_from(AgentAction).where(AgentAction.agent_name == "code_review_agent")
                )
                stats["prs_reviewed"] = prs or 0

                # Docs generated
                docs = await session.scalar(
                    select(func.count()).select_from(AgentAction).where(AgentAction.agent_name == "docs_agent")
                )
                stats["docs_generated"] = docs or 0

                # Recent 20 events
                result = await session.execute(
                    select(WebhookEvent)
                    .order_by(WebhookEvent.created_at.desc())
                    .limit(20)
                )
                events = result.scalars().all()
                recent_events = [
                    {
                        "id": e.id,
                        "timestamp": e.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "repo_full_name": e.repo_full_name,
                        "event_type": e.event_type,
                        "action": e.action,
                        "agent_name": e.event_type == "issues" and "requirements_agent" or "code_review_agent",
                        "status": e.status,
                        "correlation_id": e.correlation_id,
                    }
                    for e in events
                ]
        except Exception as exc:
            logger.error("Dashboard DB query failed", extra={"error": str(exc)})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_events": recent_events,
        "github_repo": settings.github_repo,
        "app_name": settings.app_name,
    })
