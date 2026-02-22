"""User settings page routes."""
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth.session import get_current_user
from app.db.models import User, UserSettings
from app.db.session import AsyncSessionLocal

router = APIRouter(tags=["settings"])
templates = Jinja2Templates(directory="frontend/templates")


def _mask_key(key: str | None) -> str:
    """Show only last 4 chars of an API key."""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "************" + key[-4:]


async def _get_user_id(github_user_id: int) -> str | None:
    """Look up the internal user UUID from github_user_id."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User.id).where(User.github_user_id == github_user_id)
        )
        return result.scalar_one_or_none()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    user_id = await _get_user_id(user["github_user_id"])
    user_settings = None
    if user_id:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSettings).where(UserSettings.user_id == user_id)
            )
            user_settings = result.scalar_one_or_none()

    settings_data = {
        "openrouter_api_key_masked": _mask_key(
            user_settings.openrouter_api_key if user_settings else None
        ),
        "openrouter_model": (
            user_settings.openrouter_model
            if user_settings
            else "anthropic/claude-3.5-sonnet"
        ),
        "openai_api_key_masked": _mask_key(
            user_settings.openai_api_key if user_settings else None
        ),
        "openai_embedding_model": (
            user_settings.openai_embedding_model
            if user_settings
            else "text-embedding-3-small"
        ),
    }

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "settings": settings_data,
            "success": request.query_params.get("success"),
        },
    )


@router.post("/settings")
async def save_settings(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    user_id = await _get_user_id(user["github_user_id"])
    if not user_id:
        return RedirectResponse("/")

    form = await request.form()
    openrouter_key = (form.get("openrouter_api_key") or "").strip() or None
    openrouter_model = (
        (form.get("openrouter_model") or "").strip() or "anthropic/claude-3.5-sonnet"
    )
    openai_key = (form.get("openai_api_key") or "").strip() or None
    openai_embedding_model = (
        (form.get("openai_embedding_model") or "").strip()
        or "text-embedding-3-small"
    )

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = result.scalar_one_or_none()

        if user_settings:
            if openrouter_key:
                user_settings.openrouter_api_key = openrouter_key
            if openai_key:
                user_settings.openai_api_key = openai_key
            user_settings.openrouter_model = openrouter_model
            user_settings.openai_embedding_model = openai_embedding_model
            user_settings.updated_at = datetime.utcnow()
        else:
            import uuid

            user_settings = UserSettings(
                id=str(uuid.uuid4()),
                user_id=user_id,
                openrouter_api_key=openrouter_key,
                openrouter_model=openrouter_model,
                openai_api_key=openai_key,
                openai_embedding_model=openai_embedding_model,
            )
            session.add(user_settings)

        await session.commit()

    return RedirectResponse("/settings?success=1", status_code=303)
