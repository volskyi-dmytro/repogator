from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, Boolean, JSON, ForeignKey
from typing import Optional
from datetime import datetime
import uuid


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


class WebhookEvent(Base):
    """Stores raw GitHub webhook events received by the application."""

    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(
        String(50)
    )  # "issues" | "pull_request"
    action: Mapped[str] = mapped_column(String(50))
    repo_full_name: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), default="received"
    )  # received|processing|completed|error
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )


class AgentAction(Base):
    """Records each agent action taken in response to a webhook event."""

    __tablename__ = "agent_actions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    webhook_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("webhook_events.id")
    )
    agent_name: Mapped[str] = mapped_column(String(100))
    input_data: Mapped[dict] = mapped_column(JSON)
    output_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    github_posted: Mapped[bool] = mapped_column(Boolean, default=False)
    tokens_used: Mapped[Optional[int]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )


class AuditLog(Base):
    """Append-only audit log for all significant application events."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class User(Base):
    """GitHub OAuth user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    github_user_id: Mapped[int] = mapped_column(unique=True, index=True)
    github_login: Mapped[str] = mapped_column(String(100))
    github_avatar_url: Mapped[str] = mapped_column(String(500))
    github_access_token: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    last_login_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class TrackedRepo(Base):
    """A repository tracked by a user."""

    __tablename__ = "tracked_repos"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    repo_full_name: Mapped[str] = mapped_column(String(200), index=True)
    webhook_secret: Mapped[str] = mapped_column(String(64))
    webhook_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class UserSettings(Base):
    """Per-user configuration for API keys and model preferences."""

    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), unique=True, index=True
    )
    openrouter_api_key: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    openrouter_model: Mapped[str] = mapped_column(
        String(100), default="anthropic/claude-3.5-sonnet"
    )
    openai_api_key: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    openai_embedding_model: Mapped[str] = mapped_column(
        String(100), default="text-embedding-3-small"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class KnowledgeDocument(Base):
    """Tracks documents ingested into a user's knowledge base."""

    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(50))  # "upload" | "url" | "github_auto"
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(default=0)
    collection_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
