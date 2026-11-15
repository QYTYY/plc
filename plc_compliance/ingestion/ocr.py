"""Optional OCR backends for images, scanned PDFs, and table screenshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from plc_compliance.domain.models import RawInput
from plc_compliance.ingestion.adapters import ExtractedFact, _fact, _file_path


class PaddleOCRBackend:
    """Lazy PaddleOCR wrapper supporting both current and legacy APIs."""

    def __init__(self, *, language: str = "ch", confidence_threshold: float = 0.70) -> None:
        self.language = language
        self.confidence_threshold = confidence_threshold
        self._engine: Any = None

    @property
    def engine(self) -> Any:
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise RuntimeError("OCR 需要安装 paddleocr 和 paddlepaddle，可执行 pip install -r ingestion/requirements.txt") from exc
            try:
                self._engine = PaddleOCR(lang=self.language, use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=True)
            except TypeError:
                self._engine = PaddleOCR(lang=self.language, use_angle_cls=True)
        return self._engine

    def recognize(self, path: str | Path) -> list[dict[str, Any]]:
        image_path = str(path)
        if hasattr(self.engine, "predict"):
            result = self.engine.predict(image_path)
            return self._parse_predict(result)
        result = self.engine.ocr(image_path, cls=True)
        return self._parse_legacy(result)

    @staticmethod
    def _parse_predict(result: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in result:
            texts = page.get("rec_texts", []) if hasattr(page, "get") else getattr(page, "rec_texts", [])
            scores = page.get("rec_scores", []) if hasattr(page, "get") else getattr(page, "rec_scores", [])
            boxes = page.get("rec_boxes", []) if hasattr(page, "get") else getattr(page, "rec_boxes", [])
            for index, text in enumerate(texts):
                score = float(scores[index]) if index < len(scores) else 0.0
                box = boxes[index].tolist() if index < len(boxes) and hasattr(boxes[index], "tolist") else (boxes[index] if index < len(boxes) else [])
                rows.append({"text": str(text), "confidence": score, "box": box})
        return rows

    @staticmethod
    def _parse_legacy(result: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in result or []:
            for item in page or []:
                if len(item) < 2:
                    continue
                box, pair = item[0], item[1]
                rows.append({"text": str(pair[0]), "confidence": float(pair[1]), "box": box})
        return rows


class ImageOCRAdapter:
    """OCR adapter for PNG/JPG and other local image files."""

    _MEDIA_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp", "image/tiff"}

    def __init__(self, backend: PaddleOCRBackend | None = None) -> None:
        self.backend = backend or PaddleOCRBackend()

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type in self._MEDIA_TYPES and _file_path(raw_input) is not None

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        path = _file_path(raw_input)
        if path is None:
            return []
        facts = []
        for index, item in enumerate(self.backend.recognize(path), 1):
            facts.append(_fact(raw_input, f"bbox_{index}:{item['box']}", item["text"], "image_text", "paddleocr", confidence=item["confidence"], fields={"box": item["box"], "needs_human_review": item["confidence"] < self.backend.confidence_threshold}))
        return facts


class ScannedPDFOCRAdapter:
    """Render PDF pages to images and OCR pages without extractable text."""

    def __init__(self, backend: PaddleOCRBackend | None = None) -> None:
        self.backend = backend or PaddleOCRBackend()

    def supports(self, raw_input: RawInput) -> bool:
        return raw_input.media_type == "application/pdf" and _file_path(raw_input) is not None

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        path = _file_path(raw_input)
        if path is None:
            return []
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("扫描版 PDF OCR 需要安装 pymupdf") from exc
        facts: list[ExtractedFact] = []
        document = fitz.open(str(path))
        for page_number, page in enumerate(document, 1):
            if (page.get_text() or "").strip():
                continue
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_path = path.with_name(f".{path.stem}.ocr-page-{page_number}.png")
            pixmap.save(str(image_path))
            try:
                for index, item in enumerate(self.backend.recognize(image_path), 1):
                    facts.append(_fact(raw_input, f"page_{page_number}/bbox_{index}:{item['box']}", item["text"], "scanned_document_text", "paddleocr+pymupdf", confidence=item["confidence"], fields={"page": page_number, "box": item["box"], "needs_human_review": item["confidence"] < self.backend.confidence_threshold}))
            finally:
                image_path.unlink(missing_ok=True)
        document.close()
        return facts


class TableOCRAdapter(ImageOCRAdapter):
    """Convert OCR lines into table-row evidence while preserving coordinates."""

    def extract(self, raw_input: RawInput) -> list[ExtractedFact]:
        facts = super().extract(raw_input)
        cells: list[ExtractedFact] = []
        row_centers: list[float] = []
        for fact in facts:
            box = fact.fields.get("box", [])
            try:
                values = [float(item) for point in box for item in (point if isinstance(point, (list, tuple)) else [point])]
                center_y = (min(values[1::2]) + max(values[1::2])) / 2 if len(values) >= 4 else 0.0
            except (TypeError, ValueError):
                center_y = 0.0
            row_index = next((index for index, center in enumerate(row_centers, 1) if abs(center - center_y) <= 20), len(row_centers) + 1)
            if row_index > len(row_centers):
                row_centers.append(center_y)
            cells.append(ExtractedFact(**{**fact.__dict__, "evidence_type": "image_table_cell", "fields": {**fact.fields, "table_candidate": True, "table_row": row_index}}))
        return cells
