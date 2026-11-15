"""Role-specific views over one shared knowledge store."""

from __future__ import annotations

from plc_compliance.knowledge.models import RetrievalHit
from plc_compliance.knowledge.protocols import EmbeddingProvider, VectorStore


ROLE_KNOWLEDGE_TYPES = {
    "evidence_analyst": ["inspection_report", "historical_assessment", "operations"],
    "baseline_expert": ["standard", "baseline"],
    "risk_analyst": ["threat", "vendor_manual", "standard"],
}


class RoleRetriever:
    """Retrieve from one knowledge platform using a role-specific view."""

    def __init__(self, role: str, embeddings: EmbeddingProvider, vector_store: VectorStore) -> None:
        self.role = role
        self.embeddings = embeddings
        self.vector_store = vector_store

    def search(self, query: str, *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        filters = dict(filters or {})
        allowed = ROLE_KNOWLEDGE_TYPES.get(self.role)
        if allowed and "knowledge_type" not in filters:
            # The vector store protocol accepts one value; callers can create one
            # retriever per source family when the production backend supports lists.
            filters["knowledge_type"] = allowed[0]
        return self.vector_store.search(self.embeddings.embed(query), top_k=top_k, filters=filters)
