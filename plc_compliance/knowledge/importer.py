"""Batch knowledge-source importer."""

from __future__ import annotations

from pathlib import Path

from plc_compliance.knowledge.loaders import FileKnowledgeLoader
from plc_compliance.knowledge.models import KnowledgeChunk, KnowledgeType
from plc_compliance.knowledge.service import KnowledgeService


class KnowledgeSourceImporter:
    """Scan a directory, load supported files, and index their chunks."""

    _SUPPORTED = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".html", ".htm", ".txt", ".md", ".log", ".json"}

    def __init__(self, service: KnowledgeService | None = None) -> None:
        self.service = service or KnowledgeService()
        self.loader = FileKnowledgeLoader()

    def import_directory(self, directory: str | Path) -> dict[str, list[KnowledgeChunk]]:
        """Index every supported file and return chunks grouped by source."""
        root = Path(directory)
        result: dict[str, list[KnowledgeChunk]] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in self._SUPPORTED:
                document_id = f"DOC-{path.relative_to(root).as_posix().replace('/', '-')}"
                document = self.loader.load(path, document_id=document_id)
                result[str(path)] = self.service.ingest(document)
        return result
