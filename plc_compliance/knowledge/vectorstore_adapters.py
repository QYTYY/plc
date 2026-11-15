"""Adapters for production vector stores with LangChain-compatible APIs."""

from __future__ import annotations

from plc_compliance.knowledge.models import KnowledgeChunk, RetrievalHit


class LangChainVectorStoreAdapter:
    """Adapt a vector store exposing ``add_texts`` and vector similarity search."""

    def __init__(self, store: object) -> None:
        self.store = store

    def upsert(self, chunks: list[KnowledgeChunk]) -> None:
        add_texts = getattr(self.store, "add_texts", None)
        if add_texts is None:
            raise TypeError("Vector store must provide add_texts(texts, metadatas=...)")
        add_texts(
            [chunk.content for chunk in chunks],
            metadatas=[{
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "knowledge_type": chunk.knowledge_type,
                "source": chunk.source,
                "locator": chunk.locator,
                "version": chunk.version or "",
                "asset_types": ",".join(chunk.asset_types),
                "industries": ",".join(chunk.industries),
            } for chunk in chunks],
        )

    def search(self, query_vector: list[float], *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        search = getattr(self.store, "similarity_search_by_vector_with_relevance_scores", None)
        if search is None:
            raise TypeError("Vector store must provide similarity_search_by_vector_with_relevance_scores")
        documents = search(query_vector, k=top_k, filter=filters)
        hits: list[RetrievalHit] = []
        for document, score in documents:
            metadata = document.metadata
            chunk = KnowledgeChunk(
                chunk_id=metadata["chunk_id"],
                document_id=metadata["document_id"],
                content=document.page_content,
                knowledge_type=metadata["knowledge_type"],
                source=metadata["source"],
                locator=metadata["locator"],
                version=metadata.get("version") or None,
                asset_types=[item for item in metadata.get("asset_types", "").split(",") if item],
                industries=[item for item in metadata.get("industries", "").split(",") if item],
            )
            hits.append(RetrievalHit(chunk=chunk, score=float(score)))
        return hits
