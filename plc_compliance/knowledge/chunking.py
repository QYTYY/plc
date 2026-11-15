"""Semantic chunking that preserves document locations."""

from __future__ import annotations

import re

from plc_compliance.knowledge.models import KnowledgeChunk, KnowledgeDocument


class SemanticChunker:
    """Split documents by headings and paragraphs with a bounded fallback size."""

    def __init__(self, max_chars: int = 1800) -> None:
        self.max_chars = max_chars

    def chunk(self, document: KnowledgeDocument) -> list[KnowledgeChunk]:
        sections = re.split(r"\n\s*(?=(?:第?[一二三四五六七八九十0-9]+[章节条]|[0-9]+(?:\.[0-9]+)+))", document.content)
        chunks: list[KnowledgeChunk] = []
        for index, section in enumerate(sections, 1):
            text = section.strip()
            if not text:
                continue
            for part_index, start in enumerate(range(0, len(text), self.max_chars), 1):
                part = text[start:start + self.max_chars].strip()
                if not part:
                    continue
                chunks.append(KnowledgeChunk(
                    chunk_id=f"{document.document_id}-CH-{index:04d}-{part_index:02d}",
                    document_id=document.document_id,
                    content=part,
                    knowledge_type=document.knowledge_type,
                    source=document.source,
                    locator=f"section_{index}/part_{part_index}",
                    version=document.version,
                    asset_types=document.asset_types,
                    industries=document.industries,
                    access_level=document.access_level,
                ))
        return chunks
