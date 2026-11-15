"""Embedding implementations; replace the development provider with a model API."""

from __future__ import annotations

import hashlib
import math


class LangChainEmbeddingProvider:
    """Adapter for any LangChain embeddings object supplied by the caller."""

    def __init__(self, embeddings: object) -> None:
        self.embeddings = embeddings

    def embed(self, text: str) -> list[float]:
        embed_query = getattr(self.embeddings, "embed_query", None)
        if embed_query is None:
            raise TypeError("Embedding object must provide embed_query(text)")
        return list(embed_query(text))


class FastEmbedProvider:
    """Local multilingual Embedding provider backed by FastEmbed/ONNX."""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError("Install fastembed to use the local embedding provider") from exc
        self.model_name = model_name
        self.model = TextEmbedding(model_name=model_name)
        self.dimensions = next(item["dim"] for item in TextEmbedding.list_supported_models() if item["model"] == model_name)
        self._uses_e5_prefix = "e5" in model_name.lower()

    def embed(self, text: str) -> list[float]:
        value = f"passage: {text}" if self._uses_e5_prefix else text
        return [float(item) for item in next(iter(self.model.embed([value])))]

    def embed_query(self, text: str) -> list[float]:
        value = f"query: {text}" if self._uses_e5_prefix else text
        return [float(item) for item in next(iter(self.model.query_embed([value])))]


class HashEmbeddingProvider:
    """Deterministic offline vectorizer for development and tests only."""

    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
