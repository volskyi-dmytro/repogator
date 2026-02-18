from pydantic import BaseModel
from typing import Optional


class GitHubUser(BaseModel):
    """Represents a GitHub user in webhook payloads."""

    login: str
    id: int
    avatar_url: str


class GitHubRepo(BaseModel):
    """Represents a GitHub repository in webhook payloads."""

    id: int
    name: str
    full_name: str
    private: bool
    html_url: str


class GitHubIssue(BaseModel):
    """Represents a GitHub issue in webhook payloads."""

    id: int
    number: int
    title: str
    body: Optional[str] = None
    state: str
    user: GitHubUser
    labels: list = []
    html_url: str


class GitHubPR(BaseModel):
    """Represents a GitHub pull request in webhook payloads."""

    id: int
    number: int
    title: str
    body: Optional[str] = None
    state: str
    user: GitHubUser
    head: dict
    base: dict
    html_url: str
    diff_url: str


class GitHubIssueEvent(BaseModel):
    """Represents a GitHub issues webhook event."""

    action: str
    issue: GitHubIssue
    repository: GitHubRepo
    sender: GitHubUser


class GitHubPREvent(BaseModel):
    """Represents a GitHub pull_request webhook event."""

    action: str
    pull_request: GitHubPR
    repository: GitHubRepo
    sender: GitHubUser
    number: int


class WebhookPayload(BaseModel):
    """Generic wrapper for a received webhook payload before parsing."""

    event_type: str
    raw_payload: dict
