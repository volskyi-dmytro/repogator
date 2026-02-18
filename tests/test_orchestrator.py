import pytest
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_orchestrator_routes_issues_to_requirements_agent():
    """Issues events route to requirements agent"""
    from app.agents.orchestrator import route_event, RepoGatorState

    state: RepoGatorState = {
        "event_type": "issues",
        "payload": {"action": "opened"},
        "correlation_id": "test-corr-id",
        "repo_full_name": "owner/repo",
        "agent_outputs": {},
        "github_posted": False,
        "error": None,
    }
    result = route_event(state)
    assert result == "requirements_agent"

@pytest.mark.asyncio
async def test_orchestrator_routes_prs_to_code_review_agent():
    """PR events route to code review agent"""
    from app.agents.orchestrator import route_event, RepoGatorState

    state: RepoGatorState = {
        "event_type": "pull_request",
        "payload": {"action": "opened"},
        "correlation_id": "test-corr-id",
        "repo_full_name": "owner/repo",
        "agent_outputs": {},
        "github_posted": False,
        "error": None,
    }
    result = route_event(state)
    assert result == "code_review_agent"
