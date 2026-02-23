import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from datetime import datetime
import uuid

from app.config import settings
from app.auth.session import set_session, clear_session, get_current_user
from app.db.session import AsyncSessionLocal
from app.db.models import User, UserSettings

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


@router.get("/github")
async def github_login():
    """Redirect to GitHub OAuth authorization page."""
    params = f"client_id={settings.github_client_id}&scope=read:user%20user:email"
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/callback")
async def github_callback(request: Request, code: str = "", error: str = ""):
    """Handle GitHub OAuth callback."""
    if error or not code:
        return RedirectResponse("/?error=oauth_failed")

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse("/?error=no_token")

    # Fetch GitHub user info
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        gh_user = user_resp.json()

    github_user_id = gh_user.get("id")
    github_login = gh_user.get("login", "")
    github_avatar_url = gh_user.get("avatar_url", "")

    if not github_user_id:
        return RedirectResponse("/?error=no_user_id")

    # Upsert user in DB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.github_user_id == github_user_id)
        )
        user = result.scalar_one_or_none()

        if user:
            user.github_login = github_login
            user.github_avatar_url = github_avatar_url
            user.github_access_token = access_token
            user.last_login_at = datetime.utcnow()
        else:
            user = User(
                id=str(uuid.uuid4()),
                github_user_id=github_user_id,
                github_login=github_login,
                github_avatar_url=github_avatar_url,
                github_access_token=access_token,
            )
            session.add(user)
            await session.flush()
            # Create default UserSettings
            user_settings = UserSettings(
                id=str(uuid.uuid4()),
                user_id=user.id,
            )
            session.add(user_settings)

        await session.commit()
        user_id = user.id

    # Set session cookie
    response = RedirectResponse("/dashboard")
    set_session(response, {
        "user_id": user_id,
        "github_user_id": github_user_id,
        "github_login": github_login,
        "github_avatar_url": github_avatar_url,
        "github_access_token": access_token,
    })
    return response


@router.get("/expand-scope")
async def expand_scope(request: Request, repo: str = ""):
    """Redirect to GitHub OAuth with expanded scope (for webhook installation)."""
    import urllib.parse
    state = urllib.parse.quote(f"repo:{repo}") if repo else ""
    params = f"client_id={settings.github_client_id}&scope=read:user+user:email+write:repo_hook"
    if state:
        params += f"&state={state}"
    return RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}")


@router.get("/expand-callback")
async def expand_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Handle GitHub OAuth callback for expanded scope."""
    if error or not code:
        return RedirectResponse("/repos?error=oauth_failed")

    # Exchange code for access token (same as regular callback)
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse("/repos?error=no_token")

    # Get current user from session
    user_session = get_current_user(request)
    if not user_session:
        return RedirectResponse("/?error=not_logged_in")

    # Update access token in DB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_session["user_id"])
        )
        user = result.scalar_one_or_none()
        if user:
            user.github_access_token = access_token
            await session.commit()

    # Update session with new token
    import urllib.parse
    pending_repo = ""
    if state.startswith("repo:"):
        pending_repo = urllib.parse.unquote(state[5:])

    response_url = f"/repos?success=scope_expanded"
    if pending_repo:
        response_url += f"&pending_repo={urllib.parse.quote(pending_repo)}"

    response = RedirectResponse(response_url)
    # Update session token
    new_session_data = dict(user_session)
    new_session_data["github_access_token"] = access_token
    set_session(response, new_session_data)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/")
    clear_session(response)
    return response
