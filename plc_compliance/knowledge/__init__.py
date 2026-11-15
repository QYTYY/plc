"""Knowledge ingestion, structured baselines, and role-aware retrieval."""

from plc_compliance.knowledge.models import KnowledgeChunk, KnowledgeDocument, RetrievalHit
from plc_compliance.knowledge.importer import KnowledgeSourceImporter
from plc_compliance.knowledge.structured_extractor import CandidateRuleExtractor
from plc_compliance.knowledge.retrievers import RoleRetriever
from plc_compliance.knowledge.service import KnowledgeService
from plc_compliance.knowledge.structured import BaselineKnowledgeStore, InMemoryBaselineKnowledgeStore
from plc_compliance.knowledge.vectorstore_adapters import LangChainVectorStoreAdapter

__all__ = [
    "BaselineKnowledgeStore",
    "InMemoryBaselineKnowledgeStore",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeService",
    "KnowledgeSourceImporter",
    "CandidateRuleExtractor",
    "LangChainVectorStoreAdapter",
    "RoleRetriever",
    "RetrievalHit",
]
