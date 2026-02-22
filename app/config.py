from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    # App
    app_name: str = "RepoGator"
    debug: bool = False
    testing: bool = False

    # GitHub
    github_token: str
    github_webhook_secret: str
    github_repo: str  # e.g. "owner/repo"

    # Database
    database_url: str  # postgresql+asyncpg://...

    # Redis
    redis_url: str = "redis://localhost:6379"

    # OpenRouter (LLM)
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "anthropic/claude-3.5-sonnet"

    # OpenAI (embeddings)
    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-small"

    # ChromaDB
    chromadb_host: str = "localhost"
    chromadb_port: int = 8001

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""
    session_secret_key: str = "change-me-in-production-use-secrets-token-hex-32"

    # App base URL (for webhook callbacks)
    app_base_url: str = "https://repogator.gojoble.online"

    # Queue
    webhook_queue_name: str = "repogator:webhook_events"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
