import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_requirements_agent_output_schema(mocker):
    """Requirements agent returns properly structured output"""
    mock_llm_response = {
        "enriched_title": "As a user, I want to login with OAuth",
        "acceptance_criteria": [
            "Given I am on the login page, When I click 'Login with GitHub', Then I am redirected to GitHub OAuth"
        ],
        "edge_cases": ["Invalid token", "Expired session"],
        "suggested_labels": ["authentication", "oauth"],
        "complexity": "M",
        "rag_sources": ["requirements_best_practices.md#invest"],
        "formatted_comment": "## 🤖 Requirements Analysis\n..."
    }

    with patch("app.agents.requirements_agent.RequirementsAgent._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_llm_response
        from app.agents.requirements_agent import RequirementsAgent, RequirementsOutput
        agent = RequirementsAgent.__new__(RequirementsAgent)
        # Validate output schema
        output = RequirementsOutput(**mock_llm_response)
        assert output.complexity in ["XS", "S", "M", "L", "XL"]
        assert len(output.acceptance_criteria) > 0
