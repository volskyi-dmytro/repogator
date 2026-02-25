"""Privacy and data governance routes.

Provides:
  GET  /privacy                  — Privacy information page (HTML)
  GET  /api/user/data/export     — Export user data summary as JSON (authenticated)
  DELETE /api/user/data          — Erase all user data (GDPR right to erasure, authenticated)
"""
import logging
import uuid as _uuid
from datetime import datetime

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete as sa_delete, func

from app.auth.session import get_current_user, SESSION_COOKIE
from app.config import settings
from app.db.models import (
    AuditLog,
    KnowledgeDocument,
    TrackedRepo,
    User,
    UserSettings,
    WebhookEvent,
)
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["privacy"])
templates = Jinja2Templates(directory="frontend/templates")
logger = logging.getLogger(__name__)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    user = get_current_user(request)
    return templates.TemplateResponse("privacy.html", {
        "request": request,
        "user": user,
        "app_name": settings.app_name,
        "retention_days": settings.data_retention_days,
    })


@router.get("/api/user/data/export")
async def export_user_data(request: Request):
    """Return a JSON summary of all data RepoGator holds for the authenticated user."""
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    user_id = user["user_id"]

    async with AsyncSessionLocal() as session:
        # User profile
        result = await session.execute(select(User).where(User.id == user_id))
        db_user = result.scalar_one_or_none()

        # Tracked repos
        result = await session.execute(
            select(TrackedRepo).where(TrackedRepo.user_id == user_id)
        )
        repos = result.scalars().all()

        # Knowledge document count
        result = await session.execute(
            select(func.count()).select_from(KnowledgeDocument).where(
                KnowledgeDocument.user_id == user_id
            )
        )
        doc_count = result.scalar()

        # Webhook event count
        result = await session.execute(
            select(func.count()).select_from(WebhookEvent).where(
                WebhookEvent.repo_full_name.in_(
                    [r.repo_full_name for r in repos]
                )
            )
        )
        event_count = result.scalar()

    return JSONResponse({
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": {
            "github_login": db_user.github_login if db_user else user.get("github_login"),
            "github_email": db_user.github_email if db_user else None,
            "github_avatar_url": db_user.github_avatar_url if db_user else user.get("github_avatar_url"),
            "created_at": db_user.created_at.isoformat() if db_user else None,
            "last_login_at": db_user.last_login_at.isoformat() if db_user else None,
        },
        "tracked_repositories": [
            {
                "repo_full_name": r.repo_full_name,
                "is_active": r.is_active,
                "added_at": r.created_at.isoformat(),
            }
            for r in repos
        ],
        "knowledge_documents_count": doc_count,
        "webhook_events_count": event_count,
        "data_retention_days": settings.data_retention_days,
    })


@router.delete("/api/user/data")
async def delete_user_data(request: Request):
    """Permanently erase all data for the authenticated user (GDPR right to erasure).

    Deletes in order:
    1. ChromaDB collections (per-user knowledge base)
    2. GitHub webhooks on tracked repos (best-effort, failures are logged not raised)
    3. All PostgreSQL records for this user
    4. The user record itself
    5. Clears the session cookie

    This action is irreversible.
    """
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    user_id = user["user_id"]
    github_token = user.get("github_access_token")
    errors = []

    logger.info("Starting data erasure for user %s", user_id)

    # 1. Delete ChromaDB collections for this user
    try:
        from app.rag.knowledge_base import KnowledgeBase
        from app.db.models import UserSettings as _UserSettings

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(_UserSettings).where(_UserSettings.user_id == user_id)
            )
            user_settings = result.scalar_one_or_none()

        openai_key = (user_settings.openai_api_key if user_settings else None) or settings.openai_api_key
        embedding_model = (
            (user_settings.openai_embedding_model if user_settings else None)
            or settings.openai_embedding_model
        )

        kb = KnowledgeBase(
            host=settings.chromadb_host,
            port=settings.chromadb_port,
            openai_api_key=openai_key,
            embedding_model=embedding_model,
            user_id=user_id,
        )

        collection_types = ["requirements", "code_review", "documentation", "general", "docs"]
        for col_type in collection_types:
            col_name = f"{col_type}_{user_id}"
            try:
                kb.client.delete_collection(col_name)
                logger.info("Deleted ChromaDB collection %s", col_name)
            except Exception:
                pass  # Collection may not exist — that's fine

    except Exception as exc:
        msg = f"ChromaDB cleanup partially failed: {exc}"
        logger.warning(msg)
        errors.append(msg)

    # 2. Uninstall GitHub webhooks (best-effort)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrackedRepo).where(TrackedRepo.user_id == user_id)
        )
        repos = result.scalars().all()

    if github_token:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for repo in repos:
                if repo.webhook_id:
                    try:
                        owner, repo_name = repo.repo_full_name.split("/", 1)
                        resp = await client.delete(
                            f"https://api.github.com/repos/{repo.repo_full_name}/hooks/{repo.webhook_id}",
                            headers={
                                "Authorization": f"token {github_token}",
                                "Accept": "application/vnd.github.v3+json",
                            },
                        )
                        if resp.status_code not in (204, 404):
                            errors.append(
                                f"GitHub webhook removal for {repo.repo_full_name} "
                                f"returned {resp.status_code}"
                            )
                    except Exception as exc:
                        msg = f"Could not remove webhook for {repo.repo_full_name}: {exc}"
                        logger.warning(msg)
                        errors.append(msg)

    # 3. Delete all PostgreSQL records for this user
    async with AsyncSessionLocal() as session:
        # Delete webhook events for all tracked repos
        if repos:
            repo_names = [r.repo_full_name for r in repos]
            await session.execute(
                sa_delete(WebhookEvent).where(
                    WebhookEvent.repo_full_name.in_(repo_names)
                )
            )

        await session.execute(
            sa_delete(KnowledgeDocument).where(KnowledgeDocument.user_id == user_id)
        )
        await session.execute(
            sa_delete(TrackedRepo).where(TrackedRepo.user_id == user_id)
        )
        await session.execute(
            sa_delete(UserSettings).where(UserSettings.user_id == user_id)
        )

        # Write audit entry before deleting the user
        session.add(AuditLog(
            id=str(_uuid.uuid4()),
            correlation_id="user-erasure",
            level="INFO",
            message=f"User {user.get('github_login', user_id)} requested full data erasure",
            context={
                "user_id": user_id,
                "github_login": user.get("github_login"),
                "repos_count": len(repos),
                "errors": errors,
            },
        ))

        await session.execute(
            sa_delete(User).where(User.id == user_id)
        )
        await session.commit()

    logger.info("Data erasure complete for user %s", user_id)

    # 4. Clear the session
    response = JSONResponse({
        "success": True,
        "message": "Your account and all associated data have been permanently deleted.",
        "warnings": errors,
    })
    response.delete_cookie(SESSION_COOKIE)
    return response
