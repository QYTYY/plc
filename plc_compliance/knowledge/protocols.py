"""Replaceable interfaces for parsing, embedding, storage, and retrieval."""

from __future__ import annotations

from typing import Protocol

from plc_compliance.domain.models import BaselineRule
from plc_compliance.knowledge.models import KnowledgeChunk, KnowledgeDocument, RetrievalHit


class DocumentLoader(Protocol):
    """Convert a source file into a registered knowledge document."""

    def load(self, source: str, *, document_id: str, title: str, knowledge_type: str) -> KnowledgeDocument:
        """Load and classify one document."""


class EmbeddingProvider(Protocol):
    """Generate vectors for knowledge chunks and queries."""

    def embed(self, text: str) -> list[float]:
        """Return an embedding vector."""


class VectorStore(Protocol):
    """Store and search embedded knowledge chunks."""

    def upsert(self, chunks: list[KnowledgeChunk]) -> None:
        """Insert or replace chunks."""

    def search(self, query_vector: list[float], *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        """Return the most relevant chunks."""


class BaselineResolver(Protocol):
    """Resolve structured, versioned baseline rules."""

    def resolve(self, query: str, *, version: str | None = None) -> list[BaselineRule]:
        """Return applicable baseline rules."""
