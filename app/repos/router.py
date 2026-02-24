"""Repo management routes."""
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth.session import get_current_user
from app.config import settings
from app.db.models import KnowledgeDocument, TrackedRepo, User, UserSettings
from app.db.session import AsyncSessionLocal
from app.github.webhooks import check_repo_access, delete_webhook, install_webhook

router = APIRouter(tags=["repos"])
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/repos", response_class=HTMLResponse)
async def list_repos(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrackedRepo)
            .where(TrackedRepo.user_id == user["user_id"])
            .order_by(TrackedRepo.created_at.desc())
        )
        repos = result.scalars().all()

    repos_data = [
        {
            "id": r.id,
            "repo_full_name": r.repo_full_name,
            "is_active": r.is_active,
            "webhook_url": f"{settings.app_base_url}/webhook/{r.repo_full_name}",
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for r in repos
    ]

    return templates.TemplateResponse("repos.html", {
        "request": request,
        "repos": repos_data,
        "user": user,
        "error": request.query_params.get("error"),
        "success": request.query_params.get("success"),
    })


async def auto_ingest_repo_docs(repo_full_name: str, user_id: str, github_token: str) -> None:
    """Fetch and ingest documentation files from a newly tracked repo."""
    import asyncio
    import hashlib
    import uuid as _uuid
    from datetime import datetime
    import base64
    import httpx
    from app.rag.knowledge_base import KnowledgeBase
    from app.rag.ingest import ingest_document
    from app.config import settings as _settings

    # Files to fetch with their collection types
    target_files = [
        ("CONTRIBUTING.md", "code_review"),
        ("ARCHITECTURE.md", "docs"),
        ("SECURITY.md", "code_review"),
        ("README.md", "general"),
    ]

    # Get user settings for KB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = result.scalar_one_or_none()

    openai_key = (user_settings.openai_api_key if user_settings else None) or _settings.openai_api_key
    embedding_model = (user_settings.openai_embedding_model if user_settings else None) or _settings.openai_embedding_model

    kb = KnowledgeBase(
        host=_settings.chromadb_host,
        port=_settings.chromadb_port,
        openai_api_key=openai_key,
        embedding_model=embedding_model,
        user_id=user_id,
    )

    headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        for filename, collection_type in target_files:
            try:
                url = f"https://api.github.com/repos/{repo_full_name}/contents/{filename}"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()

                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                import logging as _logging
                _logging.getLogger(__name__).info("Fetched %s from %s: %d chars", filename, repo_full_name, len(content))
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                html_url = data.get("html_url", url)

                # Skip duplicate
                async with AsyncSessionLocal() as session:
                    existing = await session.execute(
                        select(KnowledgeDocument).where(
                            KnowledgeDocument.user_id == user_id,
                            KnowledgeDocument.content_hash == content_hash,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                doc_id = str(_uuid.uuid4())
                title = f"{repo_full_name}/{filename}"

                chunk_count = await ingest_document(
                    kb=kb,
                    content=content,
                    user_id=user_id,
                    collection_type=collection_type,
                    title=title,
                    source_type="github_auto",
                    document_id=doc_id,
                    metadata={"repo": repo_full_name, "filename": filename},
                )

                async with AsyncSessionLocal() as session:
                    doc = KnowledgeDocument(
                        id=doc_id,
                        user_id=user_id,
                        title=title,
                        source_type="github_auto",
                        source_url=html_url,
                        filename=filename,
                        content_hash=content_hash,
                        chunk_count=chunk_count,
                        collection_type=collection_type,
                        status="ingested",
                        last_ingested_at=datetime.utcnow(),
                    )
                    session.add(doc)
                    await session.commit()

                import logging as _logging
                _logging.getLogger(__name__).info("Auto-ingested %s from %s (%d chunks)", filename, repo_full_name, chunk_count)

            except Exception as e:
                import logging as _logging
                _logging.getLogger(__name__).warning("Failed to auto-ingest %s from %s: %s", filename, repo_full_name, str(e))

            await asyncio.sleep(0.5)

        # Also try docs/*.md (up to 10 files)
        try:
            docs_url = f"https://api.github.com/repos/{repo_full_name}/contents/docs"
            resp = await client.get(docs_url, headers=headers)
            if resp.status_code == 200:
                docs_listing = resp.json()
                md_files = [f for f in docs_listing if isinstance(f, dict) and f.get("name", "").endswith(".md")][:10]
                for file_info in md_files:
                    try:
                        file_resp = await client.get(file_info["url"], headers=headers)
                        file_resp.raise_for_status()
                        file_data = file_resp.json()
                        content = base64.b64decode(file_data["content"]).decode("utf-8", errors="replace")
                        content_hash = hashlib.sha256(content.encode()).hexdigest()
                        html_url = file_data.get("html_url", file_info["url"])
                        filename = file_info["name"]

                        async with AsyncSessionLocal() as session:
                            existing = await session.execute(
                                select(KnowledgeDocument).where(
                                    KnowledgeDocument.user_id == user_id,
                                    KnowledgeDocument.content_hash == content_hash,
                                )
                            )
                            if existing.scalar_one_or_none():
                                continue

                        doc_id = str(_uuid.uuid4())
                        title = f"{repo_full_name}/docs/{filename}"
                        chunk_count = await ingest_document(
                            kb=kb, content=content, user_id=user_id,
                            collection_type="docs", title=title,
                            source_type="github_auto", document_id=doc_id,
                            metadata={"repo": repo_full_name, "filename": filename},
                        )
                        async with AsyncSessionLocal() as session:
                            doc = KnowledgeDocument(
                                id=doc_id, user_id=user_id, title=title,
                                source_type="github_auto", source_url=html_url,
                                filename=filename, content_hash=content_hash,
                                chunk_count=chunk_count, collection_type="docs",
                                status="ingested", last_ingested_at=datetime.utcnow(),
                            )
                            session.add(doc)
                            await session.commit()
                    except Exception as e:
                        import logging as _logging
                        _logging.getLogger(__name__).warning("Failed to ingest docs/%s: %s", file_info.get("name"), str(e))
                    await asyncio.sleep(0.5)
        except Exception:
            pass


@router.post("/repos")
async def add_repo(request: Request, background_tasks: BackgroundTasks):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    form = await request.form()
    repo_full_name = (form.get("repo_full_name") or "").strip()

    if not repo_full_name or "/" not in repo_full_name:
        return RedirectResponse("/repos?error=invalid_repo_name", status_code=303)

    token = user["github_access_token"]

    # Check access
    has_access = await check_repo_access(token, repo_full_name)
    if not has_access:
        return RedirectResponse("/repos?error=no_access", status_code=303)

    webhook_secret = secrets.token_hex(32)
    owner, repo_name = repo_full_name.split("/", 1)
    webhook_url = f"{settings.app_base_url}/webhook/{owner}/{repo_name}"

    # Install webhook on GitHub
    webhook_id = await install_webhook(token, repo_full_name, webhook_url, webhook_secret)

    async with AsyncSessionLocal() as session:
        # Check for existing (deactivated) entry
        result = await session.execute(
            select(TrackedRepo).where(
                TrackedRepo.user_id == user["user_id"],
                TrackedRepo.repo_full_name == repo_full_name,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.webhook_secret = webhook_secret
            existing.webhook_id = webhook_id
            existing.is_active = True
        else:
            repo = TrackedRepo(
                id=str(uuid.uuid4()),
                user_id=user["user_id"],
                repo_full_name=repo_full_name,
                webhook_secret=webhook_secret,
                webhook_id=webhook_id,
                is_active=True,
                created_at=datetime.utcnow(),
            )
            session.add(repo)

        await session.commit()

    background_tasks.add_task(auto_ingest_repo_docs, repo_full_name, user["user_id"], token)

    return RedirectResponse("/repos?success=repo_added", status_code=303)


@router.delete("/repos/{repo_id}")
async def delete_repo(request: Request, repo_id: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(TrackedRepo).where(
                TrackedRepo.id == repo_id,
                TrackedRepo.user_id == user["user_id"],
            )
        )
        repo = result.scalar_one_or_none()

        if not repo:
            return RedirectResponse("/repos?error=not_found", status_code=303)

        # Delete webhook from GitHub if we have the ID
        if repo.webhook_id:
            await delete_webhook(user["github_access_token"], repo.repo_full_name, repo.webhook_id)

        repo.is_active = False
        repo.webhook_id = None
        await session.commit()

    return RedirectResponse("/repos?success=repo_removed", status_code=303)


@router.post("/repos/{repo_id}/delete")
async def delete_repo_form(request: Request, repo_id: str):
    """HTML form-compatible delete (since browsers don't support DELETE from forms)."""
    return await delete_repo(request, repo_id)
