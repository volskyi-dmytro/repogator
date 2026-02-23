# 🐊 RepoGator

RepoGator is an AI-powered GitHub automation SaaS that lets users connect their own repositories and get automated issue enrichment, pull request reviews, and documentation generation — all driven by AI agents running in the background. Users authenticate with GitHub OAuth, add repositories they own, and optionally supply their own OpenRouter/OpenAI API keys. The system installs webhooks automatically and processes events through a LangGraph orchestrator backed by a per-user ChromaDB RAG store.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     GitHub Repository                        │
│              (Issues, Pull Requests, Events)                 │
└──────────────────────────┬──────────────────────────────────┘
                           │ Webhooks (per-repo HMAC secret)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  POST /webhook/{owner}/{repo} → Verify → DB Log → Queue     │
│  POST /webhook (legacy, global secret)                      │
└──────────────┬────────────────────────────┬─────────────────┘
               │                            │
               ▼                            ▼
┌──────────────────────┐      ┌─────────────────────────────┐
│   LangGraph          │      │      Web UI                  │
│   Orchestrator       │      │   GET /          landing     │
│   (per-user keys)    │      │   GET /dashboard (authed)   │
│                      │      │   GET /repos                 │
│  ┌────────────────┐  │      │   GET /settings              │
│  │Requirements    │  │      │   GET /knowledge             │
│  │Agent (Issues)  │  │      │   GET /auth/github           │
│  └────────────────┘  │      └─────────────────────────────┘
│  ┌────────────────┐  │
│  │Code Review     │  │      ┌─────────────────────────────┐
│  │Agent (PRs)     │  │      │   Infrastructure             │
│  └────────────────┘  │      │  ├── PostgreSQL (DB)        │
│  ┌────────────────┐  │      │  ├── Redis (job queue)      │
│  │Docs Agent      │  │      │  ├── ChromaDB (per-user)    │
│  └────────────────┘  │      │  └── nginx (reverse proxy)  │
└──────────────────────┘      └─────────────────────────────┘
```

## What It Does

Users sign in with their GitHub account via OAuth (minimal `read:user user:email` scope — no scary full-repo permissions dialog). After login they can add any repo they have access to — at that point RepoGator requests `write:repo_hook` scope via incremental authorization, then auto-installs the webhook on GitHub (scoped to issues and pull_request events) with a unique HMAC secret per repo. When events arrive, the LangGraph orchestrator dispatches the right agent: the Requirements Agent enriches issues with acceptance criteria and complexity estimates, the Code Review Agent reviews PRs against codebase conventions from the RAG store, and the Docs Agent generates context-aware documentation summaries. All output is posted back to GitHub as structured comments.

Each user has their own knowledge base in ChromaDB. Agents query the user's collection first and fall back to the shared default collection if the user's KB is empty or low-confidence. When a repo is added, RepoGator automatically ingests its documentation files (CONTRIBUTING.md, ARCHITECTURE.md, SECURITY.md, README.md, docs/*.md) into the user's knowledge base in the background.

Users can supply their own OpenRouter and OpenAI API keys in the Settings page so agent calls are billed to their own accounts. If no keys are provided, the system falls back to the admin keys.

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Server | FastAPI + Uvicorn | Webhook receiver, web UI, health checks |
| Auth | GitHub OAuth + itsdangerous | Signed session cookies, incremental scope |
| Orchestration | LangGraph | Stateful multi-agent workflow |
| LLM | OpenRouter (Claude 3.5 Sonnet) | Agent reasoning and structured output |
| Embeddings | OpenAI text-embedding-3-small | RAG vector search |
| Vector Store | ChromaDB | Per-user RAG knowledge base with shared fallback |
| Job Queue | Redis | Async webhook event processing |
| Database | PostgreSQL + SQLAlchemy | Users, repos, events, knowledge docs, audit log |
| Reverse Proxy | nginx | Reverse proxy, SSL via Cloudflare origin cert |
| Containerization | Docker + Docker Compose | Local dev and production deployment |
| CI/CD | GitHub Actions | Automated test, build, deploy |

## Quick Start

```bash
# 1. Clone and enter the project
git clone https://github.com/volskyi-dmytro/repogator.git && cd repogator

# 2. Copy and fill in environment variables
cp .env.example .env
# Edit .env — see Environment Variables table below

# 3. Start all services
docker compose up -d

# 4. Ingest the shared knowledge base into ChromaDB (one-time)
docker exec repogator-app python -m scripts.ingest_knowledge_base

# 5. Verify the app is running
curl http://localhost:8000/health

# 6. Visit http://localhost:8000 and log in with GitHub
```

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `GITHUB_TOKEN` | Admin token for legacy `/webhook` endpoint | Yes | `ghp_xxxxxxxxxxxx` |
| `GITHUB_WEBHOOK_SECRET` | Secret for legacy `/webhook` endpoint | Yes | `my-random-secret` |
| `GITHUB_REPO` | Default repo for legacy mode | Yes | `octocat/hello-world` |
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID | Yes | `Ov23lixxxxxxxxxx` |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret | Yes | `abc123...` |
| `SESSION_SECRET_KEY` | Secret for signing session cookies | Yes | `secrets.token_hex(32)` |
| `DATABASE_URL` | PostgreSQL async connection string | Yes | `postgresql+asyncpg://user:pass@localhost/repogator` |
| `REDIS_URL` | Redis connection URL | Yes | `redis://localhost:6379` |
| `OPENROUTER_API_KEY` | Fallback LLM key (admin mode) | Yes | `sk-or-xxxxxxxxxxxx` |
| `OPENAI_API_KEY` | Fallback embeddings key (admin mode) | Yes | `sk-xxxxxxxxxxxx` |
| `APP_BASE_URL` | Public base URL for webhook callbacks | No | `https://repogator.gojoble.online` |
| `CHROMADB_HOST` | ChromaDB service hostname | No | `localhost` |
| `CHROMADB_PORT` | ChromaDB service port | No | `8001` |
| `OPENROUTER_MODEL` | Default LLM model | No | `anthropic/claude-3.5-sonnet` |
| `DEBUG` | Enable debug logging | No | `false` |

## GitHub OAuth App Setup

1. Go to **github.com → Settings → Developer settings → OAuth Apps → New OAuth App**
2. Set **Authorization callback URL** to `https://your-domain/auth/callback`
3. Set **Additional callback URL** to `https://your-domain/auth/expand-callback` (for incremental scope)
4. Copy the **Client ID** (starts with `Ov23li...`) and a generated **Client Secret** into your `.env`

> Note: The Client ID starts with the letter **O** (not the digit 0). They look identical in some fonts.

## GitHub Secrets for CI/CD

The CI/CD pipeline (`.github/workflows/deploy.yml`) runs **test → build → deploy** on every push to `main`.

| Secret | Description |
|--------|-------------|
| `DOCKER_USERNAME` | Docker Hub username |
| `DOCKER_PASSWORD` | Docker Hub access token |
| `VPS_HOST` | IP or hostname of deployment VPS |
| `VPS_USER` | SSH username on the VPS |
| `VPS_SSH_KEY` | Private SSH key for VPS deployment |

## Event Processing

Webhook events follow this lifecycle:

1. `POST /webhook/{owner}/{repo}` — per-repo HMAC signature verified, event persisted with `status=received`, pushed to Redis queue along with the user's API keys
2. Queue worker pops the event, dispatches through LangGraph orchestrator using the user's keys (falls back to admin keys if unset)
3. The appropriate agent processes the event, querying the user's ChromaDB collection first (falls back to shared collection)
4. Agent posts a comment back to GitHub, DB record updated to `status=completed` or `status=failed`

On container restart, events with `status=received` are automatically re-queued so no events are lost between deployments.

## Knowledge Base

Each user has isolated knowledge base collections in ChromaDB. Agents query the user's collection first; if confidence is low, they merge results from the shared default collection as a fallback.

Users manage their knowledge base at `/knowledge`:

- **Upload files** — `.md`, `.txt`, or `.pdf` (max 10 MB), assigned to a collection type (Requirements / Code Review / Documentation / General)
- **Index a URL** — paste any public URL; RepoGator fetches and indexes the content (max 500 KB)
- **Auto-ingestion** — when a repo is added, RepoGator automatically fetches and indexes `CONTRIBUTING.md`, `ARCHITECTURE.md`, `SECURITY.md`, `README.md`, and `docs/*.md` from that repo in the background

Collection types map to agent usage: `requirements` → Requirements Agent, `code_review` → Code Review Agent, `docs` → Docs Agent, `general` → all agents.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/` | None | Landing page |
| `GET` | `/dashboard` | Session | Event feed and stats for user's repos |
| `GET` | `/repos` | Session | List tracked repositories |
| `POST` | `/repos` | Session | Add repo (triggers incremental OAuth → installs webhook → auto-ingests docs) |
| `POST` | `/repos/{id}/delete` | Session | Remove repo and delete its webhook |
| `GET` | `/settings` | Session | View/edit API key configuration |
| `POST` | `/settings` | Session | Save API keys and model preferences |
| `GET` | `/knowledge` | Session | Knowledge base management page |
| `GET` | `/knowledge/list` | Session | List user's knowledge documents (JSON) |
| `POST` | `/knowledge/upload` | Session | Upload and index a file |
| `POST` | `/knowledge/url` | Session | Fetch and index a URL |
| `DELETE` | `/knowledge/{id}` | Session | Delete a knowledge document |
| `GET` | `/auth/github` | None | Redirect to GitHub OAuth (minimal scope) |
| `GET` | `/auth/callback` | None | OAuth callback — sets session, redirects to dashboard |
| `GET` | `/auth/expand-scope` | None | Re-initiate OAuth with `write:repo_hook` scope |
| `GET` | `/auth/expand-callback` | None | Expanded-scope callback — updates token, resumes repo add |
| `GET` | `/auth/logout` | None | Clear session, redirect to landing |
| `POST` | `/webhook/{owner}/{repo}` | HMAC | Per-repo webhook endpoint |
| `POST` | `/webhook` | HMAC | Legacy webhook endpoint (global secret) |
| `GET` | `/health` | None | Health check for all services |

## Live Instance

[https://repogator.gojoble.online/](https://repogator.gojoble.online/)

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
