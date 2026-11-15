"""RAG interfaces. Replace the placeholder provider with your vector/search service."""

from __future__ import annotations

from typing import Protocol


class RAGProvider(Protocol):
    """Role-specific knowledge retrieval contract."""

    def search(self, query: str, *, top_k: int = 5) -> list[str]:
        """Return relevant, source-identifiable knowledge snippets."""


class PlaceholderRAG:
    """Small offline provider used until a real RAG backend is connected."""

    def __init__(self, name: str) -> None:
        self.name = name

    def search(self, query: str, *, top_k: int = 5) -> list[str]:
        del top_k
        return [f"[{self.name}] 当前未配置知识库，无法检索：{query}"]


class RoleAwareRAG:
    """Role-specific view over the shared knowledge service."""

    _TYPES = {
        "evidence_analyst": {"inspection_report", "operations"},
        "baseline_expert": {"baseline", "standard", "vendor_manual"},
        "risk_analyst": {"threat", "baseline", "standard"},
    }

    def __init__(self, service: object, role: str) -> None:
        self.service = service
        self.role = role

    def search(self, query: str, *, top_k: int = 5) -> list[str]:
        hits = []
        for knowledge_type in self._TYPES.get(self.role, set()):
            hits.extend(self.service.search(query, top_k=top_k, filters={"knowledge_type": knowledge_type}))
        hits.sort(key=lambda item: item.score, reverse=True)
        return [f"[{item.chunk.source}#{item.chunk.locator}] {item.chunk.content}" for item in hits[:top_k]]
