"""GitHub API client with retry logic."""
import httpx
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class GitHubClient:
    """Async GitHub API client with exponential backoff retry."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request_with_retry(self, method: str, url: str, max_retries: int = 3, **kwargs) -> dict:
        """Make HTTP request with exponential backoff retry (3x)."""
        last_exception = None
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(headers=self.headers, timeout=30.0) as client:
                    response = await getattr(client, method)(url, **kwargs)
                    response.raise_for_status()
                    return response.json()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as e:
                last_exception = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403, 404):
                    raise  # Don't retry auth/not found errors
                wait_time = (2 ** attempt) + 0.5
                logger.warning(f"GitHub API attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                await asyncio.sleep(wait_time)
        raise last_exception

    async def post_comment(self, repo: str, issue_number: int, body: str) -> dict:
        """Post a comment to a GitHub issue or pull request.

        Args:
            repo: Full repository name "owner/repo".
            issue_number: Issue or PR number.
            body: Markdown comment body.

        Returns:
            Created comment object from GitHub API.
        """
        url = f"{self.BASE_URL}/repos/{repo}/issues/{issue_number}/comments"
        return await self._request_with_retry("post", url, json={"body": body})

    async def add_label(self, repo: str, issue_number: int, labels: list[str]) -> dict:
        """Add labels to a GitHub issue or pull request."""
        url = f"{self.BASE_URL}/repos/{repo}/issues/{issue_number}/labels"
        return await self._request_with_retry("post", url, json={"labels": labels})

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """Get the unified diff of a pull request.

        Returns:
            Raw diff text (truncated to 65000 chars to stay within LLM context).
        """
        url = f"{self.BASE_URL}/repos/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            # GitHub returns diff when Accept header is text/plain
            response = await client.get(url, headers={
                **self.headers,
                "Accept": "application/vnd.github.v3.diff"
            })
            response.raise_for_status()
            diff = response.text
            # Truncate to avoid LLM context limits
            return diff[:65000] if len(diff) > 65000 else diff

    async def get_issue(self, repo: str, issue_number: int) -> dict:
        """Get issue details from GitHub."""
        url = f"{self.BASE_URL}/repos/{repo}/issues/{issue_number}"
        return await self._request_with_retry("get", url)

    async def get_pr(self, repo: str, pr_number: int) -> dict:
        """Get pull request details from GitHub."""
        url = f"{self.BASE_URL}/repos/{repo}/pulls/{pr_number}"
        return await self._request_with_retry("get", url)
