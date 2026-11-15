"""Input-to-evidence orchestration and normalization."""

from __future__ import annotations

import hashlib

from plc_compliance.domain.models import Evidence, RawInput
from plc_compliance.ingestion.adapters import (
    CommandOutputAdapter,
    ConfigFileAdapter,
    ContentBlockAdapter,
    DocumentTextAdapter,
    ExtractedFact,
    ImageInputAdapter,
    InputAdapter,
    LogAdapter,
    SpreadsheetAdapter,
    TextInputAdapter,
)


class EvidenceNormalizer:
    """Convert extraction facts into stable, traceable Evidence objects."""

    def normalize(self, facts: list[ExtractedFact]) -> list[Evidence]:
        evidence: list[Evidence] = []
        seen: set[str] = set()
        for fact in facts:
            digest = hashlib.sha1(f"{fact.source_input_id}:{fact.location}:{fact.content}".encode()).hexdigest()[:12]
            evidence_id = f"EV-{digest}"
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            evidence.append(Evidence(
                evidence_id=evidence_id,
                source=fact.source,
                location=fact.location,
                content=fact.content,
                evidence_type=fact.evidence_type,
                confidence=max(0.0, min(1.0, fact.confidence)),
                source_input_id=fact.source_input_id,
                extraction_method=fact.extraction_method,
            ))
        return evidence


class EvidenceIngestionService:
    """Run format adapters and preserve unsupported inputs for Intake Agent."""

    def __init__(self, adapters: list[InputAdapter] | None = None) -> None:
        self.adapters = adapters or [
            CommandOutputAdapter(),
            ConfigFileAdapter(),
            SpreadsheetAdapter(),
            DocumentTextAdapter(),
            LogAdapter(),
            TextInputAdapter(),
            ContentBlockAdapter(),
            ImageInputAdapter(),
        ]
        self.normalizer = EvidenceNormalizer()

    def extract(self, raw_inputs: list[RawInput]) -> list[Evidence]:
        """Extract deterministic facts and normalize them into Evidence."""
        facts: list[ExtractedFact] = []
        for raw_input in raw_inputs:
            adapter = next((item for item in self.adapters if item.supports(raw_input)), None)
            if adapter is not None:
                facts.extend(adapter.extract(raw_input))
        return self.normalizer.normalize(facts)

    @staticmethod
    def merge(primary: list[Evidence], additional: list[Evidence]) -> list[Evidence]:
        """Merge deterministic and Agent-extracted evidence by evidence ID."""
        merged = {item.evidence_id: item for item in primary}
        for item in additional:
            merged.setdefault(item.evidence_id, item)
        return list(merged.values())
