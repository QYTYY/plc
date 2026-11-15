"""Knowledge-layer data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


KnowledgeType = Literal["standard", "baseline", "vendor_manual", "inspection_report", "threat", "operations", "historical_assessment"]


class KnowledgeDocument(BaseModel):
    """A registered source document before chunking and indexing."""

    document_id: str
    title: str
    source: str
    media_type: str
    knowledge_type: KnowledgeType
    version: str | None = None
    asset_types: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    access_level: str = "internal"
    content: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeChunk(BaseModel):
    """A retrievable, source-cited semantic unit."""

    chunk_id: str
    document_id: str
    content: str
    knowledge_type: KnowledgeType
    source: str
    locator: str
    version: str | None = None
    asset_types: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    access_level: str = "internal"
    metadata: dict[str, str] = Field(default_factory=dict)
    embedding: list[float] | None = None


class RetrievalHit(BaseModel):
    """A chunk returned by a retriever with a score and citation."""

    chunk: KnowledgeChunk
    score: float
