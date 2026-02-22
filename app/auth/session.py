from typing import Optional
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import settings

_serializer = URLSafeTimedSerializer(settings.session_secret_key)
SESSION_COOKIE = "rg_session"
MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def set_session(response, data: dict) -> None:
    token = _serializer.dumps(data)
    response.set_cookie(SESSION_COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax")


def clear_session(response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def get_session(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> Optional[dict]:
    """Returns session dict with github_user_id, github_login, github_avatar_url, github_access_token or None."""
    return get_session(request)


def require_user(request: Request) -> dict:
    """Returns session dict or raises _NotLoggedIn if not logged in."""
    user = get_current_user(request)
    if not user:
        raise _NotLoggedIn()
    return user


class _NotLoggedIn(Exception):
    pass
