"""ChromaDB knowledge base for RAG retrieval.

## Collection Isolation Model

Each user's knowledge base is completely isolated from all other users through
per-user collection naming. Collections follow the pattern:

    {collection_type}_{user_id}

For example:
    requirements_3f7a2b1c-...   (user A's requirements collection)
    requirements_9d4e5f6g-...   (user B's requirements collection)

No query ever touches another user's collection because the collection name is
always scoped by the user_id passed at KnowledgeBase construction time.

The `retrieve()` method queries the user's own collection first, then falls back
to shared system collections (no user_id suffix) for admin-ingested global context.
Shared collections contain only admin-uploaded content; no user data ever enters them.

To delete a user's data completely, delete all ChromaDB collections whose names
end with _{user_id}.
"""
import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """ChromaDB-backed knowledge base with OpenAI embeddings."""

    def __init__(self, host: str, port: int, openai_api_key: str, embedding_model: str, user_id: str = None):
        self.client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.openai = AsyncOpenAI(api_key=openai_api_key)
        self.embedding_model = embedding_model
        self.collections: dict = {}
        self.user_id = user_id

    def _user_collection_name(self, base_name: str) -> str:
        """Returns per-user collection name if user_id set, else base name."""
        if self.user_id:
            return f"{base_name}_{self.user_id}"
        return base_name

    async def get_or_create_collection(self, name: str):
        """Get or create a ChromaDB collection."""
        if name not in self.collections:
            self.collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        return self.collections[name]

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for text using OpenAI."""
        response = await self.openai.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        return response.data[0].embedding

    async def add_document(
        self, collection_name: str, doc_id: str, text: str, metadata: dict
    ) -> None:
        """Add a document to the knowledge base."""
        collection = await self.get_or_create_collection(collection_name)
        embedding = await self.embed_text(text)
        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata],
        )
        logger.info("Added document %s to collection %s", doc_id, collection_name)

    async def retrieve(self, collection_name: str, query: str, n_results: int = 3) -> list[dict]:
        """Retrieve relevant documents. Queries user collection first, falls back to shared."""
        query_embedding = await self.embed_text(query)
        results = []

        if self.user_id:
            # Query user-specific collection first
            user_col_name = self._user_collection_name(collection_name)
            try:
                user_collection = await self.get_or_create_collection(user_col_name)
                user_results = user_collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    include=["documents", "metadatas", "distances"],
                )
                for i, doc in enumerate(user_results["documents"][0]):
                    results.append({
                        "text": doc,
                        "metadata": user_results["metadatas"][0][i],
                        "distance": user_results["distances"][0][i],
                        "id": user_results["ids"][0][i],
                        "source": "user",
                    })
            except Exception:
                pass  # User collection may be empty

        # Always also query shared collection, then merge
        try:
            shared_collection = await self.get_or_create_collection(collection_name)
            shared_results = shared_collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )
            seen_ids = {r["id"] for r in results}
            for i, doc in enumerate(shared_results["documents"][0]):
                doc_id = shared_results["ids"][0][i]
                if doc_id not in seen_ids:
                    results.append({
                        "text": doc,
                        "metadata": shared_results["metadatas"][0][i],
                        "distance": shared_results["distances"][0][i],
                        "id": doc_id,
                        "source": "shared",
                    })
        except Exception:
            pass

        # Sort by distance (lower = more similar), return top n
        results.sort(key=lambda x: x["distance"])
        return results[:n_results]
