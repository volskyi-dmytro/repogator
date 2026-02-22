import pytest
from unittest.mock import AsyncMock, patch


def test_requirements_agent_output_schema():
    """RequirementsOutput schema validates correctly structured data."""
    from app.agents.requirements_agent import RequirementsOutput

    data = {
        "enriched_title": "As a user, I want to login with OAuth",
        "acceptance_criteria": [
            "Given I am on the login page, When I click 'Login with GitHub', Then I am redirected to GitHub OAuth"
        ],
        "edge_cases": ["Invalid token", "Expired session"],
        "suggested_labels": ["authentication", "oauth"],
        "complexity": "M",
        "rag_sources": ["requirements_best_practices.md#invest"],
        "formatted_comment": "## 🤖 Requirements Analysis\n...",
    }

    output = RequirementsOutput(**data)
    assert output.complexity in ["XS", "S", "M", "L", "XL"]
    assert len(output.acceptance_criteria) > 0
    assert len(output.edge_cases) > 0
    assert len(output.suggested_labels) > 0
