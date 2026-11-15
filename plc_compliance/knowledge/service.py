"""Knowledge ingestion and retrieval service."""

from __future__ import annotations

from plc_compliance.knowledge.chunking import SemanticChunker
from plc_compliance.knowledge.embeddings import HashEmbeddingProvider
from plc_compliance.knowledge.models import KnowledgeChunk, KnowledgeDocument, RetrievalHit
from plc_compliance.knowledge.protocols import EmbeddingProvider, VectorStore
from plc_compliance.knowledge.vectorstore import InMemoryVectorStore


class KnowledgeService:
    """Coordinate chunking, embedding, and vector storage."""

    def __init__(self, embeddings: EmbeddingProvider | None = None, vector_store: VectorStore | None = None) -> None:
        self.embeddings = embeddings or HashEmbeddingProvider()
        self.vector_store = vector_store or InMemoryVectorStore()
        self.chunker = SemanticChunker()

    def ingest(self, document: KnowledgeDocument) -> list[KnowledgeChunk]:
        """Chunk and index one document, returning indexed chunks."""
        chunks = self.chunker.chunk(document)
        for chunk in chunks:
            chunk.embedding = self.embeddings.embed(chunk.content)
        self.vector_store.upsert(chunks)
        return chunks

    def search(self, query: str, *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        """Search indexed knowledge with metadata filters."""
        embed_query = getattr(self.embeddings, "embed_query", self.embeddings.embed)
        return self.vector_store.search(embed_query(query), top_k=top_k, filters=filters)
