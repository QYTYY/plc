"""Load heterogeneous files into KnowledgeDocument objects."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from plc_compliance.domain.models import RawInput
from plc_compliance.ingestion.adapters import (
    CommandOutputAdapter,
    ConfigFileAdapter,
    DocumentTextAdapter,
    LogAdapter,
    SpreadsheetAdapter,
    TextInputAdapter,
)
from plc_compliance.knowledge.models import KnowledgeDocument, KnowledgeType


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


class FileKnowledgeLoader:
    """Read supported source files and preserve their text for indexing."""

    _TYPE_BY_FOLDER: dict[str, KnowledgeType] = {
        "industry_baselines": "baseline",
        "iec_62443": "standard",
        "vendor_manuals": "vendor_manual",
        "inspection_samples": "inspection_report",
        "threat_intelligence": "threat",
        "operations": "operations",
        "risk_frameworks": "standard",
    }

    def load(self, path: str | Path, *, document_id: str, knowledge_type: KnowledgeType | None = None) -> KnowledgeDocument:
        file_path = Path(path)
        media_type = self._media_type(file_path)
        content = self._read_content(file_path, media_type)
        kind = knowledge_type or self._infer_knowledge_type(file_path)
        return KnowledgeDocument(
            document_id=document_id,
            title=file_path.stem,
            source=str(file_path),
            media_type=media_type,
            knowledge_type=kind,
            content=content,
        )

    def _read_content(self, path: Path, media_type: str) -> str:
        if media_type == "text/html":
            parser = _TextCollector()
            parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
            return "\n".join(parser.parts)
        if media_type in {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"}:
            raw = RawInput(input_id=path.name, source=str(path), content=str(path), media_type=media_type)
            adapters = [DocumentTextAdapter(), SpreadsheetAdapter()]
            facts = next((adapter.extract(raw) for adapter in adapters if adapter.supports(raw)), [])
            return "\n".join(fact.content for fact in facts)
        return path.read_text(encoding="utf-8", errors="ignore")

    def _infer_knowledge_type(self, path: Path) -> KnowledgeType:
        for parent in path.parents:
            if parent.name in self._TYPE_BY_FOLDER:
                return self._TYPE_BY_FOLDER[parent.name]
        return "standard"

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel",
            ".html": "text/html",
            ".htm": "text/html",
            ".csv": "text/csv",
            ".log": "text/log",
            ".json": "application/json",
        }.get(path.suffix.lower(), "text/plain")
