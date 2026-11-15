"""Multimodal input adapters and evidence normalization."""

from plc_compliance.ingestion.service import EvidenceIngestionService, EvidenceNormalizer
from plc_compliance.ingestion.ocr import ImageOCRAdapter, ScannedPDFOCRAdapter, TableOCRAdapter

__all__ = ["EvidenceIngestionService", "EvidenceNormalizer", "ImageOCRAdapter", "ScannedPDFOCRAdapter", "TableOCRAdapter"]
