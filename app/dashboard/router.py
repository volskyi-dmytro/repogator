"""Dashboard router for RepoGator monitoring UI."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func

from app.config import settings
from app.db.models import WebhookEvent, AgentAction, TrackedRepo
from app.db.session import AsyncSessionLocal
from app.auth.session import get_current_user
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Serve the landing page for anonymous visitors."""
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "app_name": settings.app_name,
    })


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Protected dashboard — shows stats and events for current user's repos only."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

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
                # Get user's tracked repo names
                repos_result = await session.execute(
                    select(TrackedRepo.repo_full_name).where(
                        TrackedRepo.user_id == user["user_id"],
                        TrackedRepo.is_active == True,
                    )
                )
                user_repos = [r[0] for r in repos_result.fetchall()]

                if user_repos:
                    # Total events for user's repos
                    total = await session.scalar(
                        select(func.count()).select_from(WebhookEvent).where(
                            WebhookEvent.repo_full_name.in_(user_repos)
                        )
                    )
                    stats["total_events"] = total or 0

                    # Issues enriched
                    issues = await session.scalar(
                        select(func.count()).select_from(AgentAction)
                        .join(WebhookEvent, AgentAction.webhook_event_id == WebhookEvent.id)
                        .where(
                            AgentAction.agent_name == "requirements_agent",
                            WebhookEvent.repo_full_name.in_(user_repos),
                        )
                    )
                    stats["issues_enriched"] = issues or 0

                    # PRs reviewed
                    prs = await session.scalar(
                        select(func.count()).select_from(AgentAction)
                        .join(WebhookEvent, AgentAction.webhook_event_id == WebhookEvent.id)
                        .where(
                            AgentAction.agent_name == "code_review_agent",
                            WebhookEvent.repo_full_name.in_(user_repos),
                        )
                    )
                    stats["prs_reviewed"] = prs or 0

                    # Docs generated
                    docs = await session.scalar(
                        select(func.count()).select_from(AgentAction)
                        .join(WebhookEvent, AgentAction.webhook_event_id == WebhookEvent.id)
                        .where(
                            AgentAction.agent_name == "docs_agent",
                            WebhookEvent.repo_full_name.in_(user_repos),
                        )
                    )
                    stats["docs_generated"] = docs or 0

                    # Recent 20 events for user's repos
                    result = await session.execute(
                        select(WebhookEvent)
                        .where(WebhookEvent.repo_full_name.in_(user_repos))
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
                            "agent_name": "requirements_agent" if e.event_type == "issues" else "code_review_agent",
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
        "user": user,
    })
