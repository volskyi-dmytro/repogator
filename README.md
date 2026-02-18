# 🐊 RepoGator

RepoGator is an AI-powered GitHub automation system that listens to repository events via webhooks and dispatches specialized AI agents to enrich issues, review pull requests, and generate documentation — then posts structured analysis directly back to GitHub. It combines a FastAPI backend with a LangGraph orchestrator to coordinate multiple agents, each backed by a ChromaDB RAG store for context-aware output. The result is a fully automated engineering assistant that works in the background of any GitHub repository.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Repository                        │
│              (Issues, Pull Requests, Events)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ Webhooks
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  POST /webhook → Signature Verify → DB Log → Redis Queue    │
└──────────────┬────────────────────────────┬─────────────────┘
               │                            │
               ▼                            ▼
┌──────────────────────┐      ┌─────────────────────────────┐
│   LangGraph          │      │      Dashboard               │
│   Orchestrator       │      │   GET / (dark theme UI)     │
│                      │      │   GET /health               │
│  ┌────────────────┐  │      └─────────────────────────────┘
│  │Requirements    │  │
│  │Agent (Issues)  │  │      ┌─────────────────────────────┐
│  └────────────────┘  │      │   Infrastructure             │
│  ┌────────────────┐  │      │  ├── PostgreSQL (audit log) │
│  │Code Review     │  │      │  ├── Redis (job queue)      │
│  │Agent (PRs)     │  │      │  ├── ChromaDB (RAG store)   │
│  └────────────────┘  │      │  └── nginx (reverse proxy)  │
│  ┌────────────────┐  │      └─────────────────────────────┘
│  │Docs Agent      │  │
│  └────────────────┘  │
└──────────────────────┘
```

## What It Does

RepoGator connects to your GitHub repository via webhooks and automatically triages incoming issues by enriching them with acceptance criteria, complexity estimates, and edge cases — posting the analysis as a structured comment. When pull requests are opened, the Code Review Agent performs an AI-powered review referencing your codebase conventions from the RAG store. The Docs Agent can detect documentation gaps and generate or update relevant docs, all coordinated by a LangGraph state machine that ensures each event is handled by the right agent.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Server | FastAPI + Uvicorn | Webhook receiver, dashboard, health checks |
| Orchestration | LangGraph | Stateful multi-agent workflow |
| LLM | OpenRouter (Claude 3.5 Sonnet) | Agent reasoning and structured output |
| Embeddings | OpenAI text-embedding-3-small | RAG vector search |
| Vector Store | ChromaDB | RAG knowledge base for agents |
| Job Queue | Redis | Async webhook event processing |
| Database | PostgreSQL + SQLAlchemy | Audit log, event tracking |
| Reverse Proxy | nginx | TLS termination, routing |
| Containerization | Docker + Docker Compose | Local dev and production deployment |
| CI/CD | GitHub Actions | Automated test, build, deploy |
| GitHub Integration | PyGitHub + webhook HMAC | Event ingestion, comment posting |

## Quick Start

```bash
# 1. Clone and enter the project
git clone https://github.com/your-org/repogator.git && cd repogator

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env with your GitHub token, webhook secret, OpenRouter key, etc.

# 3. Start all services
docker compose up -d

# 4. Verify the app is running
curl http://localhost:8000/health

# 5. Point your GitHub webhook to http://your-server:8000/webhook
#    with Content-Type: application/json and your GITHUB_WEBHOOK_SECRET
```

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `GITHUB_TOKEN` | Personal access token with repo permissions | Yes | `ghp_xxxxxxxxxxxx` |
| `GITHUB_WEBHOOK_SECRET` | Secret used to verify webhook signatures | Yes | `my-random-secret` |
| `GITHUB_REPO` | Target repository in owner/repo format | Yes | `octocat/hello-world` |
| `DATABASE_URL` | PostgreSQL async connection string | Yes | `postgresql+asyncpg://user:pass@localhost/repogator` |
| `REDIS_URL` | Redis connection URL | Yes | `redis://localhost:6379` |
| `OPENROUTER_API_KEY` | API key for OpenRouter LLM calls | Yes | `sk-or-xxxxxxxxxxxx` |
| `OPENAI_API_KEY` | API key for OpenAI embeddings | Yes | `sk-xxxxxxxxxxxx` |
| `CHROMADB_HOST` | ChromaDB service hostname | No | `localhost` |
| `CHROMADB_PORT` | ChromaDB service port | No | `8001` |
| `OPENROUTER_MODEL` | LLM model name via OpenRouter | No | `anthropic/claude-3.5-sonnet` |
| `DEBUG` | Enable debug logging | No | `false` |

## GitHub Secrets for CI/CD

| Secret | Description |
|--------|-------------|
| `DOCKER_USERNAME` | Docker Hub username for image push |
| `DOCKER_PASSWORD` | Docker Hub access token |
| `VPS_HOST` | IP or hostname of deployment VPS |
| `VPS_USER` | SSH username on the VPS (e.g. `ubuntu`) |
| `VPS_SSH_KEY` | Private SSH key for VPS deployment |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook` | Receive GitHub webhook events (HMAC verified) |
| `GET` | `/` | Dashboard UI — live event feed and stats |
| `GET` | `/health` | Health check for all services (JSON response) |

## Demo

![Dashboard](docs/dashboard-screenshot.png)

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the test suite
pytest tests/ -v

# Run with live reload during development
uvicorn app.main:app --reload --port 8000
```

## License

MIT
