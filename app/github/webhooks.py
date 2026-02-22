"""GitHub webhook management helpers."""
import httpx
from typing import Optional


async def install_webhook(
    token: str,
    repo_full_name: str,
    webhook_url: str,
    secret: str,
) -> Optional[int]:
    """Install a webhook on a GitHub repo. Returns webhook_id or None on failure."""
    url = f"https://api.github.com/repos/{repo_full_name}/hooks"
    payload = {
        "name": "web",
        "active": True,
        "events": ["issues", "pull_request"],
        "config": {
            "url": webhook_url,
            "content_type": "json",
            "secret": secret,
            "insecure_ssl": "0",
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10.0,
        )
    if resp.status_code == 201:
        return resp.json().get("id")
    return None


async def delete_webhook(token: str, repo_full_name: str, webhook_id: int) -> bool:
    """Delete a webhook from a GitHub repo. Returns True on success."""
    url = f"https://api.github.com/repos/{repo_full_name}/hooks/{webhook_id}"
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=10.0,
        )
    return resp.status_code == 204


async def check_repo_access(token: str, repo_full_name: str) -> bool:
    """Check if user has access to a repo. Returns True if accessible."""
    url = f"https://api.github.com/repos/{repo_full_name}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10.0,
        )
    return resp.status_code == 200
