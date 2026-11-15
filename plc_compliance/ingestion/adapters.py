"""Format adapters that produce extraction facts before normalization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re
from dataclasses import dataclass, field
from typing import Protocol

from plc_compliance.domain.models import RawInput


@dataclass(frozen=True)
class ExtractedFact:
    """An intermediate fact retaining extraction provenance."""

    source_input_id: str
    source: str
    location: str
    content: str
    evidence_type: str
    confidence: float
    extraction_method: str
    fields: dict[str, object] = field(default_factory=dict)


class InputAdapter(Protocol):
    """Extract intermediate facts from one input format."""

    def supports(self, raw_input: RawInput) -> bool:
        """Return whether this adapter can process the input."""

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        """Extract facts while preserving source locations."""


def _fact(raw_input: RawInput, location: str, content: str, evidence_type: str, method: str, *, confidence: float = 1.0, fields: dict[str, object] | None = None) -> ExtractedFact:
    return ExtractedFact(
        source_input_id=raw_input.input_id,
        source=raw_input.source,
        location=location,
        content=content,
        evidence_type=evidence_type,
        confidence=confidence,
        extraction_method=method,
        fields=fields or {},
    )


def _lines(raw_input: RawInput) -> list[tuple[int, str]]:
    if not isinstance(raw_input.content, str):
        return []
    return [(number, line.strip()) for number, line in enumerate(raw_input.content.splitlines(), 1) if line.strip()]


def _file_path(raw_input: RawInput) -> Path | None:
    """Resolve a local file from ``source`` or a path-like content value."""
    candidates = [raw_input.source]
    if isinstance(raw_input.content, str):
        candidates.append(raw_input.content)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def _key_value(line: str) -> tuple[str, str] | None:
    match = re.match(r"^\s*([A-Za-z0-9_.:/-]+)\s*(?:=|:|\s{2,})\s*(.*?)\s*$", line)
    return match.groups() if match else None


class TextInputAdapter:
    """Parse plain text into lines or key/value facts."""

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in {"text/plain", "text/markdown", "text/csv"}

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        for line_number, line in _lines(raw_input):
            fields: dict[str, object] = {}
            if pair := _key_value(line):
                fields = {"field": pair[0], "value": pair[1]}
            facts.append(_fact(raw_input, f"line_{line_number}", line, "text", "text_line", fields=fields))
        return facts


class CommandOutputAdapter:
    """Parse command output while retaining line locations and key/value fields."""

    _MEDIA_TYPES = {"text/command", "application/command-output", "text/x-shell"}

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in self._MEDIA_TYPES

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        for line_number, line in _lines(raw_input):
            pair = _key_value(line)
            facts.append(_fact(
                raw_input,
                f"line_{line_number}",
                line,
                "command_output",
                "command_line",
                fields={"field": pair[0], "value": pair[1]} if pair else {},
            ))
        return facts


class ContentBlockAdapter:
    """Extract text blocks from provider-native multimodal messages."""

    def supports(self, raw_input: RawInput) -> bool:
        return isinstance(raw_input.content, list)

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        if not isinstance(raw_input.content, list):
            return []
        facts: list[ExtractedFact] = []
        for index, block in enumerate(raw_input.content, 1):
            text = block.get("text") if block.get("type") == "text" else None
            if isinstance(text, str) and text.strip():
                facts.append(_fact(raw_input, f"content_block_{index}", text.strip(), "multimodal_text", "content_block", confidence=0.9))
        return facts


class ImageInputAdapter:
    """Register image inputs for Intake Agent; pixels are not guessed here."""

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type.startswith("image/")

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        return []


class DocumentTextAdapter:
    """Extract text and tables from real PDF and Word files."""

    _MEDIA_TYPES = {"application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in self._MEDIA_TYPES

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        path = _file_path(raw_input)
        if path is None:
            return [
                _fact(raw_input, f"line_{number}", line, "document_text", "document_text", confidence=0.9)
                for number, line in _lines(raw_input)
            ]
        if raw_input.media_type == "application/pdf":
            return self._extract_pdf(raw_input, path)
        return self._extract_docx(raw_input, path)

    @staticmethod
    def _extract_pdf(raw_input: RawInput, path: Path) -> list[ExtractedFact]:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF parsing requires the 'pypdf' package") from exc
        facts: list[ExtractedFact] = []
        for page_number, page in enumerate(PdfReader(str(path)).pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                facts.append(_fact(raw_input, f"page_{page_number}", text, "document_text", "pypdf", confidence=0.9))
        return facts

    @staticmethod
    def _extract_docx(raw_input: RawInput, path: Path) -> list[ExtractedFact]:
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("Word parsing requires the 'python-docx' package") from exc
        document = Document(str(path))
        facts: list[ExtractedFact] = []
        for number, paragraph in enumerate(document.paragraphs, 1):
            if paragraph.text.strip():
                facts.append(_fact(raw_input, f"paragraph_{number}", paragraph.text.strip(), "document_text", "python-docx", confidence=0.95))
        for table_number, table in enumerate(document.tables, 1):
            for row_number, row in enumerate(table.rows, 1):
                values = [cell.text.strip() for cell in row.cells]
                if any(values):
                    facts.append(_fact(raw_input, f"table_{table_number}/row_{row_number}", json.dumps(values, ensure_ascii=False), "table_row", "python-docx", confidence=0.9, fields={"row": values}))
        return facts


class SpreadsheetAdapter:
    """Parse CSV or real XLSX workbooks and retain sheet/cell locations."""

    _MEDIA_TYPES = {"text/csv", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in self._MEDIA_TYPES

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        path = _file_path(raw_input)
        if path is not None and path.suffix.lower() in {".xlsx", ".xlsm"}:
            return self._extract_xlsx(raw_input, path)
        if path is not None and path.suffix.lower() == ".xls":
            return self._extract_xls(raw_input, path)
        if not isinstance(raw_input.content, str):
            return []
        rows = csv.reader(io.StringIO(raw_input.content))
        return [
            _fact(raw_input, f"row_{number}", json.dumps(row, ensure_ascii=False), "table_row", "csv_row", fields={"row": row})
            for number, row in enumerate(rows, 1)
            if row
        ]

    @staticmethod
    def _extract_xlsx(raw_input: RawInput, path: Path) -> list[ExtractedFact]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise RuntimeError("Excel parsing requires the 'openpyxl' package") from exc
        workbook = load_workbook(str(path), read_only=True, data_only=True)
        facts: list[ExtractedFact] = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows():
                values = [cell.value for cell in row]
                if not any(value is not None for value in values):
                    continue
                first_cell = row[0].coordinate
                facts.append(_fact(raw_input, f"{sheet.title}!{first_cell}: {row[-1].coordinate}", json.dumps(values, ensure_ascii=False, default=str), "table_row", "openpyxl", confidence=0.98, fields={"sheet": sheet.title, "row": values}))
        workbook.close()
        return facts

    @staticmethod
    def _extract_xls(raw_input: RawInput, path: Path) -> list[ExtractedFact]:
        try:
            import xlrd
        except ImportError as exc:
            raise RuntimeError("Legacy XLS parsing requires the 'xlrd' package") from exc
        workbook = xlrd.open_workbook(str(path), on_demand=True)
        facts: list[ExtractedFact] = []
        for sheet in workbook.sheets():
            for row_number in range(sheet.nrows):
                values = sheet.row_values(row_number)
                if not any(value != "" for value in values):
                    continue
                location = f"{sheet.name}!row_{row_number + 1}"
                facts.append(_fact(raw_input, location, json.dumps(values, ensure_ascii=False, default=str), "table_row", "xlrd", confidence=0.98, fields={"sheet": sheet.name, "row": values}))
        workbook.release_resources()
        return facts


class ConfigFileAdapter:
    """Parse JSON and simple key/value configuration content."""

    _MEDIA_TYPES = {"application/json", "application/yaml", "text/yaml", "text/ini", "application/xml"}

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in self._MEDIA_TYPES

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        if not isinstance(raw_input.content, str):
            return []
        try:
            parsed = json.loads(raw_input.content)
        except json.JSONDecodeError:
            return [
                _fact(raw_input, f"line_{number}", line, "configuration", "config_line", fields={"field": pair[0], "value": pair[1]} if (pair := _key_value(line)) else {})
                for number, line in _lines(raw_input)
            ]
        return [
            _fact(raw_input, key, json.dumps(value, ensure_ascii=False), "configuration", "json_field", fields={"field": key, "value": value})
            for key, value in parsed.items()
        ] if isinstance(parsed, dict) else []


class LogAdapter:
    """Parse log lines while preserving timestamps when present."""

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in {"text/log", "application/log"}

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        return [
            _fact(raw_input, f"line_{number}", line, "log", "log_line")
            for number, line in _lines(raw_input)
        ]
