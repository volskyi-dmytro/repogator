"""LangGraph multi-agent orchestrator for RepoGator."""
from datetime import datetime
from typing import TypedDict, Optional, Callable, Awaitable
from langgraph.graph import StateGraph, START, END
import logging
import uuid

logger = logging.getLogger(__name__)


class RepoGatorState(TypedDict):
    event_type: str          # "issues" | "pull_request"
    payload: dict
    correlation_id: str
    webhook_event_id: str
    repo_full_name: str
    agent_outputs: dict
    github_posted: bool
    error: Optional[str]


def route_event(state: RepoGatorState) -> str:
    """Route event to appropriate agent based on event_type and action."""
    event_type = state["event_type"]
    action = state["payload"].get("action", "")
    if event_type == "issues" and action == "opened":
        return "requirements_agent"
    elif event_type == "pull_request" and action == "opened":
        return "code_review_agent"
    elif event_type == "pull_request" and action == "closed" and state["payload"].get("pull_request", {}).get("merged"):
        return "docs_agent"
    else:
        return "unknown_event"


def build_graph(
    requirements_agent_fn: Callable[[RepoGatorState], Awaitable[RepoGatorState]],
    code_review_agent_fn: Callable[[RepoGatorState], Awaitable[RepoGatorState]],
    docs_agent_fn: Callable[[RepoGatorState], Awaitable[RepoGatorState]],
    post_to_github_fn: Callable[[RepoGatorState], Awaitable[RepoGatorState]],
    update_db_fn: Callable[[RepoGatorState], Awaitable[RepoGatorState]],
) -> StateGraph:
    """Build and compile the LangGraph orchestration graph.

    Graph flow:
    START -> route_event -> [requirements_agent | code_review_agent | docs_agent] -> post_to_github -> update_db -> END
    """
    workflow = StateGraph(RepoGatorState)

    # Add nodes
    workflow.add_node("requirements_agent", requirements_agent_fn)
    workflow.add_node("code_review_agent", code_review_agent_fn)
    workflow.add_node("docs_agent", docs_agent_fn)
    workflow.add_node("post_to_github", post_to_github_fn)
    workflow.add_node("update_db", update_db_fn)

    # Conditional routing from START
    workflow.add_conditional_edges(
        START,
        route_event,
        {
            "requirements_agent": "requirements_agent",
            "code_review_agent": "code_review_agent",
            "docs_agent": "docs_agent",
            "unknown_event": END,
        }
    )

    # After any agent -> post to github
    workflow.add_edge("requirements_agent", "post_to_github")
    workflow.add_edge("code_review_agent", "post_to_github")
    workflow.add_edge("docs_agent", "post_to_github")
    workflow.add_edge("post_to_github", "update_db")
    workflow.add_edge("update_db", END)

    return workflow.compile()


class RepoGatorOrchestrator:
    """Main orchestrator that wires together all agents and the graph."""

    def __init__(self, requirements_agent, code_review_agent, docs_agent, github_client, db_session_factory):
        self.requirements_agent = requirements_agent
        self.code_review_agent = code_review_agent
        self.docs_agent = docs_agent
        self.github = github_client
        self.db_session_factory = db_session_factory
        self.graph = self._build_graph()

    def _build_graph(self):
        return build_graph(
            requirements_agent_fn=self._run_requirements_agent,
            code_review_agent_fn=self._run_code_review_agent,
            docs_agent_fn=self._run_docs_agent,
            post_to_github_fn=self._post_to_github,
            update_db_fn=self._update_db,
        )

    async def _run_requirements_agent(self, state: RepoGatorState) -> RepoGatorState:
        """Node: Run requirements agent on issue event."""
        try:
            issue = state["payload"].get("issue", {})
            output = await self.requirements_agent.process(
                issue_title=issue.get("title", ""),
                issue_body=issue.get("body", ""),
                repo=state["repo_full_name"],
                correlation_id=state["correlation_id"],
            )
            return {**state, "agent_outputs": {"requirements": output.model_dump(), "issue_number": issue.get("number")}}
        except Exception as e:
            logger.error(f"Requirements agent failed: {e}", extra={"correlation_id": state["correlation_id"]})
            return {**state, "error": str(e)}

    async def _run_docs_agent(self, state: RepoGatorState) -> RepoGatorState:
        """Node: Run docs agent on merged PR event."""
        try:
            pr = state["payload"].get("pull_request", {})
            output = await self.docs_agent.process(
                title=pr.get("title", ""),
                body=pr.get("body", ""),
                diff=None,
                repo=state["repo_full_name"],
                correlation_id=state["correlation_id"],
                context_type="pull_request",
            )
            return {**state, "agent_outputs": {"docs": output.model_dump(), "pr_number": pr.get("number")}}
        except Exception as e:
            logger.error(f"Docs agent failed: {e}", extra={"correlation_id": state["correlation_id"]})
            return {**state, "error": str(e)}

    async def _run_code_review_agent(self, state: RepoGatorState) -> RepoGatorState:
        """Node: Run code review agent on PR event."""
        try:
            pr = state["payload"].get("pull_request", {})
            output = await self.code_review_agent.process(
                repo=state["repo_full_name"],
                pr_number=pr.get("number"),
                pr_title=pr.get("title", ""),
                pr_body=pr.get("body", ""),
                correlation_id=state["correlation_id"],
            )
            return {**state, "agent_outputs": {"code_review": output.model_dump(), "pr_number": pr.get("number")}}
        except Exception as e:
            logger.error(f"Code review agent failed: {e}", extra={"correlation_id": state["correlation_id"]})
            return {**state, "error": str(e)}

    async def _post_to_github(self, state: RepoGatorState) -> RepoGatorState:
        """Node: Post agent output as GitHub comment."""
        if state.get("error"):
            return state

        outputs = state["agent_outputs"]
        repo = state["repo_full_name"]

        try:
            if "requirements" in outputs:
                comment_body = outputs["requirements"]["formatted_comment"]
                issue_number = outputs["issue_number"]
                labels = outputs["requirements"]["suggested_labels"]
                await self.github.post_comment(repo, issue_number, comment_body)
                if labels:
                    await self.github.add_label(repo, issue_number, labels)

            elif "code_review" in outputs:
                comment_body = outputs["code_review"]["formatted_comment"]
                pr_number = outputs["pr_number"]
                await self.github.post_comment(repo, pr_number, comment_body)

            elif "docs" in outputs:
                comment_body = outputs["docs"]["formatted_comment"]
                pr_number = outputs["pr_number"]
                await self.github.post_comment(repo, pr_number, comment_body)

            return {**state, "github_posted": True}
        except Exception as e:
            logger.error(f"Failed to post to GitHub: {e}", extra={"correlation_id": state["correlation_id"]})
            return {**state, "error": str(e), "github_posted": False}

    async def _update_db(self, state: RepoGatorState) -> RepoGatorState:
        """Node: Insert AgentAction record with final status."""
        from app.db.models import AgentAction

        outputs = state.get("agent_outputs", {})

        # Determine agent name and extract tokens_used from whichever agent ran
        if "requirements" in outputs:
            agent_name = "requirements_agent"
            tokens_used = outputs["requirements"].get("tokens_used")
        elif "code_review" in outputs:
            agent_name = "code_review_agent"
            tokens_used = outputs["code_review"].get("tokens_used")
        elif "docs" in outputs:
            agent_name = "docs_agent"
            tokens_used = outputs["docs"].get("tokens_used")
        else:
            agent_name = "unknown"
            tokens_used = None

        status = "error" if state.get("error") else "completed"

        action = AgentAction(
            id=str(uuid.uuid4()),
            correlation_id=state["correlation_id"],
            webhook_event_id=state["webhook_event_id"],
            agent_name=agent_name,
            input_data=state["payload"],
            output_data=outputs if outputs else None,
            github_posted=state["github_posted"],
            tokens_used=tokens_used,
            status=status,
            error_message=state.get("error"),
            created_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
        )

        try:
            async with self.db_session_factory() as session:
                session.add(action)
                await session.commit()
            logger.info(
                f"AgentAction recorded. agent={agent_name} status={status} tokens={tokens_used}",
                extra={"correlation_id": state["correlation_id"]},
            )
        except Exception as e:
            logger.error(f"Failed to write AgentAction: {e}", extra={"correlation_id": state["correlation_id"]})

        return state

    async def process_event(self, event_type: str, payload: dict, correlation_id: str, repo_full_name: str, webhook_event_id: str = "") -> RepoGatorState:
        """Process a webhook event through the full agent graph."""
        initial_state: RepoGatorState = {
            "event_type": event_type,
            "payload": payload,
            "correlation_id": correlation_id,
            "webhook_event_id": webhook_event_id,
            "repo_full_name": repo_full_name,
            "agent_outputs": {},
            "github_posted": False,
            "error": None,
        }
        return await self.graph.ainvoke(initial_state)
