"""Knowledge base management routes."""
import hashlib
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, delete as sa_delete

from app.auth.session import get_current_user
from app.config import settings
from app.db.models import KnowledgeDocument, UserSettings
from app.db.session import AsyncSessionLocal
from app.rag.knowledge_base import KnowledgeBase
from app.rag.ingest import ingest_document, fetch_url_content, extract_text_from_pdf

router = APIRouter(tags=["knowledge"])
templates = Jinja2Templates(directory="frontend/templates")
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


async def _get_kb_for_user(user_id: str) -> KnowledgeBase:
    """Create a KnowledgeBase instance using the user's OpenAI key."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user_id)
        )
        user_settings = result.scalar_one_or_none()

    openai_key = (user_settings.openai_api_key if user_settings else None)
    if not openai_key:
        raise ValueError("No OpenAI API key set. Please add your key in Settings.")
    embedding_model = (user_settings.openai_embedding_model if user_settings else None) or settings.openai_embedding_model

    return KnowledgeBase(
        host=settings.chromadb_host,
        port=settings.chromadb_port,
        openai_api_key=openai_key,
        embedding_model=embedding_model,
        user_id=user_id,
    )


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/")
    return templates.TemplateResponse("knowledge.html", {
        "request": request,
        "user": user,
        "app_name": settings.app_name,
    })


@router.get("/knowledge/list")
async def list_knowledge_docs(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "not authenticated"}, status_code=401)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.user_id == user["user_id"])
            .order_by(KnowledgeDocument.created_at.desc())
        )
        docs = result.scalars().all()

    return [
        {
            "id": d.id,
            "title": d.title,
            "source_type": d.source_type,
            "source_url": d.source_url,
            "filename": d.filename,
            "chunk_count": d.chunk_count,
            "collection_type": d.collection_type,
            "status": d.status,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        for d in docs
    ]


@router.post("/knowledge/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    collection_type: str = Form(...),
):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "not authenticated"}, status_code=401)

    # Validate file extension
    allowed_exts = {".md", ".txt", ".pdf"}
    filename = file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in allowed_exts:
        return JSONResponse({"success": False, "error": f"File type not allowed. Use .md, .txt, or .pdf"}, status_code=400)

    # Read and size-check
    content_bytes = await file.read()
    if len(content_bytes) > MAX_UPLOAD_BYTES:
        return JSONResponse({"success": False, "error": "File too large (max 10MB)"}, status_code=400)

    # Extract text
    try:
        if ext == ".pdf":
            content = extract_text_from_pdf(content_bytes)
        else:
            content = content_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        return JSONResponse({"success": False, "error": f"Failed to extract text: {str(e)}"}, status_code=400)

    if not content.strip():
        return JSONResponse({"success": False, "error": "File appears to be empty"}, status_code=400)

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    user_id = user["user_id"]

    # Check for duplicate
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.content_hash == content_hash,
            )
        )
        if existing.scalar_one_or_none():
            return JSONResponse({"success": False, "error": "This document has already been indexed"}, status_code=400)

    doc_id = str(uuid.uuid4())
    title = filename or "Untitled"

    try:
        kb = await _get_kb_for_user(user_id)
        chunk_count = await ingest_document(
            kb=kb,
            content=content,
            user_id=user_id,
            collection_type=collection_type,
            title=title,
            source_type="upload",
            document_id=doc_id,
        )
    except Exception as e:
        logger.error("Failed to ingest document: %s", str(e))
        return JSONResponse({"success": False, "error": f"Ingestion failed: {str(e)}"}, status_code=500)

    # Save to DB
    async with AsyncSessionLocal() as session:
        doc = KnowledgeDocument(
            id=doc_id,
            user_id=user_id,
            title=title,
            source_type="upload",
            filename=filename,
            content_hash=content_hash,
            chunk_count=chunk_count,
            collection_type=collection_type,
            status="ingested",
            last_ingested_at=datetime.utcnow(),
        )
        session.add(doc)
        await session.commit()

    return JSONResponse({"success": True, "chunk_count": chunk_count, "doc_id": doc_id})


@router.post("/knowledge/url")
async def index_url(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "not authenticated"}, status_code=401)

    body = await request.json()
    url = (body.get("url") or "").strip()
    collection_type = body.get("collection_type", "general")

    if not url:
        return JSONResponse({"success": False, "error": "URL is required"}, status_code=400)

    try:
        content = await fetch_url_content(url)
    except Exception as e:
        return JSONResponse({"success": False, "error": f"Failed to fetch URL: {str(e)}"}, status_code=400)

    if not content.strip():
        return JSONResponse({"success": False, "error": "URL returned empty content"}, status_code=400)

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    user_id = user["user_id"]

    # Check duplicate
    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.user_id == user_id,
                KnowledgeDocument.content_hash == content_hash,
            )
        )
        if existing.scalar_one_or_none():
            return JSONResponse({"success": False, "error": "This content has already been indexed"}, status_code=400)

    doc_id = str(uuid.uuid4())
    # Use URL path as title
    from urllib.parse import urlparse
    parsed = urlparse(url)
    title = parsed.path.rstrip("/").rsplit("/", 1)[-1] or parsed.netloc or url

    try:
        kb = await _get_kb_for_user(user_id)
        chunk_count = await ingest_document(
            kb=kb,
            content=content,
            user_id=user_id,
            collection_type=collection_type,
            title=title,
            source_type="url",
            document_id=doc_id,
            metadata={"source_url": url},
        )
    except Exception as e:
        logger.error("Failed to ingest URL: %s", str(e))
        return JSONResponse({"success": False, "error": f"Ingestion failed: {str(e)}"}, status_code=500)

    async with AsyncSessionLocal() as session:
        doc = KnowledgeDocument(
            id=doc_id,
            user_id=user_id,
            title=title,
            source_type="url",
            source_url=url,
            content_hash=content_hash,
            chunk_count=chunk_count,
            collection_type=collection_type,
            status="ingested",
            last_ingested_at=datetime.utcnow(),
        )
        session.add(doc)
        await session.commit()

    return JSONResponse({"success": True, "chunk_count": chunk_count, "doc_id": doc_id})


@router.delete("/knowledge/{doc_id}")
async def delete_document(request: Request, doc_id: str):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"success": False, "error": "not authenticated"}, status_code=401)

    user_id = user["user_id"]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == doc_id,
                KnowledgeDocument.user_id == user_id,
            )
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return JSONResponse({"success": False, "error": "Document not found"}, status_code=404)

        collection_name = f"{doc.collection_type}_{user_id}"

        # Delete from ChromaDB
        try:
            kb = await _get_kb_for_user(user_id)
            collection = await kb.get_or_create_collection(collection_name)
            # Get all chunk IDs for this document
            all_items = collection.get(where={"document_id": doc_id})
            if all_items and all_items.get("ids"):
                collection.delete(ids=all_items["ids"])
        except Exception as e:
            logger.warning("Could not delete ChromaDB chunks for doc %s: %s", doc_id, str(e))

        await session.delete(doc)
        await session.commit()

    return JSONResponse({"success": True})
