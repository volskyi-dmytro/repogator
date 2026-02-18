"""Document chunking and ingestion logic for the knowledge base."""
import re
import logging
from pathlib import Path

from app.rag.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

# Minimum characters for a chunk to be worth indexing
MIN_CHUNK_LENGTH = 50


def chunk_markdown_by_section(text: str, source_file: str) -> list[dict]:
    """Split a markdown document into chunks by heading sections.

    Each heading (##, ###) starts a new chunk. The chunk includes the heading
    and all content until the next heading of equal or higher level.

    Args:
        text: Raw markdown content.
        source_file: Filename used as metadata for provenance.

    Returns:
        List of dicts with keys: id, text, metadata.
    """
    # Split on lines starting with one or more # characters
    heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    matches = list(heading_pattern.finditer(text))

    chunks = []

    if not matches:
        # No headings — treat entire document as one chunk
        if len(text.strip()) >= MIN_CHUNK_LENGTH:
            chunks.append(
                {
                    "id": f"{source_file}::0",
                    "text": text.strip(),
                    "metadata": {"source": source_file, "section": "root", "index": 0},
                }
            )
        return chunks

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk_text = text[start:end].strip()

        if len(chunk_text) < MIN_CHUNK_LENGTH:
            continue

        heading_level = len(match.group(1))
        heading_title = match.group(2).strip()
        chunk_id = f"{source_file}::{i}"

        chunks.append(
            {
                "id": chunk_id,
                "text": chunk_text,
                "metadata": {
                    "source": source_file,
                    "section": heading_title,
                    "heading_level": heading_level,
                    "index": i,
                },
            }
        )

    return chunks


async def ingest_markdown_file(
    kb: KnowledgeBase,
    file_path: Path,
    collection_name: str,
) -> int:
    """Read a markdown file, chunk it, and add all chunks to the knowledge base.

    Args:
        kb: KnowledgeBase instance to write to.
        file_path: Path to the markdown file.
        collection_name: ChromaDB collection to store chunks in.

    Returns:
        Number of chunks ingested.
    """
    text = file_path.read_text(encoding="utf-8")
    source_file = file_path.name
    chunks = chunk_markdown_by_section(text, source_file)

    for chunk in chunks:
        await kb.add_document(
            collection_name=collection_name,
            doc_id=chunk["id"],
            text=chunk["text"],
            metadata=chunk["metadata"],
        )

    logger.info("Ingested %d chunks from %s into '%s'", len(chunks), file_path, collection_name)
    return len(chunks)


async def ingest_directory(
    kb: KnowledgeBase,
    directory: Path,
    collection_name: str,
) -> int:
    """Ingest all markdown files in a directory.

    Args:
        kb: KnowledgeBase instance.
        directory: Directory containing *.md files.
        collection_name: Target ChromaDB collection.

    Returns:
        Total number of chunks ingested.
    """
    total = 0
    for md_file in sorted(directory.glob("*.md")):
        total += await ingest_markdown_file(kb, md_file, collection_name)
    logger.info("Total chunks ingested from %s: %d", directory, total)
    return total
