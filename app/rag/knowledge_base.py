"""ChromaDB knowledge base for RAG retrieval."""
import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import AsyncOpenAI
import logging

logger = logging.getLogger(__name__)


class KnowledgeBase:
    """ChromaDB-backed knowledge base with OpenAI embeddings."""

    def __init__(self, host: str, port: int, openai_api_key: str, embedding_model: str):
        self.client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.openai = AsyncOpenAI(api_key=openai_api_key)
        self.embedding_model = embedding_model
        self.collections: dict = {}

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

    async def retrieve(
        self, collection_name: str, query: str, n_results: int = 3
    ) -> list[dict]:
        """Retrieve relevant documents for a query."""
        collection = await self.get_or_create_collection(collection_name)
        query_embedding = await self.embed_text(query)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        documents = []
        for i, doc in enumerate(results["documents"][0]):
            documents.append(
                {
                    "text": doc,
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                    "id": results["ids"][0][i],
                }
            )
        return documents
