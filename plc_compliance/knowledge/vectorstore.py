"""Development vector store with metadata filtering."""

from __future__ import annotations

import math

from plc_compliance.knowledge.models import KnowledgeChunk, RetrievalHit


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right)) or 1.0
    )


class InMemoryVectorStore:
    """Small vector store for local development before pgvector/Milvus."""

    def __init__(self) -> None:
        self._chunks: dict[str, KnowledgeChunk] = {}

    def upsert(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks.update({chunk.chunk_id: chunk for chunk in chunks})

    def search(self, query_vector: list[float], *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        candidates = [chunk for chunk in self._chunks.values() if self._matches(chunk, filters or {}) and chunk.embedding]
        ranked = sorted((RetrievalHit(chunk=chunk, score=_cosine(query_vector, chunk.embedding or [])) for chunk in candidates), key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    @staticmethod
    def _matches(chunk: KnowledgeChunk, filters: dict[str, str]) -> bool:
        for key, expected in filters.items():
            if key == "knowledge_type" and chunk.knowledge_type != expected:
                return False
            if key == "version" and chunk.version != expected:
                return False
            if key == "access_level" and chunk.access_level != expected:
                return False
            if key == "asset_type" and expected not in chunk.asset_types:
                return False
            if key == "industry" and expected not in chunk.industries:
                return False
        return True


class ChromaVectorStore:
    """Persistent Chroma vector database adapter."""

    def __init__(self, path: str, collection_name: str = "plc_knowledge") -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("Install chromadb to use the persistent vector store") from exc
        client = chromadb.PersistentClient(path=path)
        self.collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            embeddings=[chunk.embedding or [] for chunk in chunks],
            metadatas=[{
                "document_id": chunk.document_id,
                "knowledge_type": chunk.knowledge_type,
                "source": chunk.source,
                "locator": chunk.locator,
                "version": chunk.version or "",
                "asset_types": ",".join(chunk.asset_types),
                "industries": ",".join(chunk.industries),
                "access_level": chunk.access_level,
            } for chunk in chunks],
        )

    def search(self, query_vector: list[float], *, top_k: int = 5, filters: dict[str, str] | None = None) -> list[RetrievalHit]:
        where = self._where(filters or {})
        result = self.collection.query(query_embeddings=[query_vector], n_results=top_k, where=where)
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        hits: list[RetrievalHit] = []
        for chunk_id, content, metadata, distance in zip(ids, documents, metadatas, distances, strict=True):
            chunk = KnowledgeChunk(
                chunk_id=chunk_id,
                document_id=metadata["document_id"],
                content=content,
                knowledge_type=metadata["knowledge_type"],
                source=metadata["source"],
                locator=metadata["locator"],
                version=metadata.get("version") or None,
                asset_types=[item for item in metadata.get("asset_types", "").split(",") if item],
                industries=[item for item in metadata.get("industries", "").split(",") if item],
                access_level=metadata.get("access_level", "internal"),
            )
            hits.append(RetrievalHit(chunk=chunk, score=1.0 - float(distance)))
        return hits

    @staticmethod
    def _where(filters: dict[str, str]) -> dict[str, object] | None:
        clauses = [{key: value} for key, value in filters.items() if key not in {"asset_type", "industry"}]
        if filters.get("asset_type"):
            clauses.append({"asset_types": {"$contains": filters["asset_type"]}})
        if filters.get("industry"):
            clauses.append({"industries": {"$contains": filters["industry"]}})
        if not clauses:
            return None
        return clauses[0] if len(clauses) == 1 else {"$and": clauses}
