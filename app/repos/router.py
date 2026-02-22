"""Repo management routes."""
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth.session import get_current_user
from app.config import settings
from app.db.models import TrackedRepo, User
from app.db.session import AsyncSessionLocal
from app.github.webhooks import check_repo_access, delete_webhook, install_webhook

router = APIRouter(tags=["repos"])
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/repos", response_class=HTMLResponse)
async def list_repos(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrackedRepo)
            .where(TrackedRepo.user_id == user["user_id"])
            .order_by(TrackedRepo.created_at.desc())
        )
        repos = result.scalars().all()

    repos_data = [
        {
            "id": r.id,
            "repo_full_name": r.repo_full_name,
            "is_active": r.is_active,
            "webhook_url": f"{settings.app_base_url}/webhook/{r.repo_full_name}",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for r in repos
    ]

    return templates.TemplateResponse("repos.html", {
        "request": request,
        "repos": repos_data,
        "user": user,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
    })


@router.post("/repos")
async def add_repo(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    form = await request.form()
    repo_full_name = (form.get("repo_full_name") or "").strip()

    if not repo_full_name or "/" not in repo_full_name:
        return RedirectResponse("/repos?error=invalid_repo_name", status_code=303)

    token = user["github_access_token"]

    # Check access
    has_access = await check_repo_access(token, repo_full_name)
    if not has_access:
        return RedirectResponse("/repos?error=no_access", status_code=303)

    webhook_secret = secrets.token_hex(32)
    owner, repo_name = repo_full_name.split("/", 1)
    webhook_url = f"{settings.app_base_url}/webhook/{owner}/{repo_name}"

    # Install webhook on GitHub
    webhook_id = await install_webhook(token, repo_full_name, webhook_url, webhook_secret)

    async with AsyncSessionLocal() as session:
        # Check for existing (deactivated) entry
        result = await session.execute(
            select(TrackedRepo).where(
                TrackedRepo.user_id == user["user_id"],
                TrackedRepo.repo_full_name == repo_full_name,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.webhook_secret = webhook_secret
            existing.webhook_id = webhook_id
            existing.is_active = True
        else:
            repo = TrackedRepo(
                id=str(uuid.uuid4()),
                user_id=user["user_id"],
                repo_full_name=repo_full_name,
                webhook_secret=webhook_secret,
                webhook_id=webhook_id,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            session.add(repo)

        await session.commit()

    return RedirectResponse("/repos?success=repo_added", status_code=303)


@router.delete("/repos/{repo_id}")
async def delete_repo(request: Request, repo_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrackedRepo).where(
                TrackedRepo.id == repo_id,
                TrackedRepo.user_id == user["user_id"],
            )
        )
        repo = result.scalar_one_or_none()

        if not repo:
            return RedirectResponse("/repos?error=not_found", status_code=303)

        # Delete webhook from GitHub if we have the ID
        if repo.webhook_id:
            await delete_webhook(user["github_access_token"], repo.repo_full_name, repo.webhook_id)

        repo.is_active = False
        repo.webhook_id = None
        await session.commit()

    return RedirectResponse("/repos?success=repo_removed", status_code=303)


@router.post("/repos/{repo_id}/delete")
async def delete_repo_form(request: Request, repo_id: str):
    """HTML form-compatible delete (since browsers don't support DELETE from forms)."""
    return await delete_repo(request, repo_id)
