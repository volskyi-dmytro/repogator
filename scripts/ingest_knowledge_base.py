#!/usr/bin/env python3
"""Ingest knowledge base markdown files into ChromaDB.

Run this script after starting ChromaDB (via docker-compose) and before
starting the application workers, so that the RAG knowledge base is
populated before agents receive their first requests.

Usage:
    python scripts/ingest_knowledge_base.py

Environment variables are loaded from .env via app/config.py settings.
"""
import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.rag.knowledge_base import KnowledgeBase
from app.rag.ingest import ingest_directory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_DIR = Path(__file__).parent.parent / "knowledge_base"

# Map collection name → subdirectory (or the root dir for a flat layout)
COLLECTIONS = {
    "requirements": KNOWLEDGE_BASE_DIR,
    "documentation": KNOWLEDGE_BASE_DIR,
    "code_review": KNOWLEDGE_BASE_DIR,
}


async def main() -> None:
    logger.info("Connecting to ChromaDB at %s:%d", settings.chromadb_host, settings.chromadb_port)
    kb = KnowledgeBase(
        host=settings.chromadb_host,
        port=settings.chromadb_port,
        openai_api_key=settings.openai_api_key,
        embedding_model=settings.openai_embedding_model,
    )

    total_chunks = 0
    for collection_name, directory in COLLECTIONS.items():
        if not directory.exists():
            logger.warning("Directory not found, skipping: %s", directory)
            continue
        logger.info("Ingesting into collection '%s' from %s", collection_name, directory)
        count = await ingest_directory(kb, directory, collection_name)
        total_chunks += count

    logger.info("Knowledge base ingestion complete. Total chunks: %d", total_chunks)


if __name__ == "__main__":
    asyncio.run(main())
