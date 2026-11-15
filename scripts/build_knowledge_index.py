"""Build a persistent local vector index and candidate baseline-rule file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plc_compliance.knowledge.embeddings import FastEmbedProvider
from plc_compliance.knowledge.importer import KnowledgeSourceImporter
from plc_compliance.knowledge.structured_extractor import CandidateRuleExtractor
from plc_compliance.knowledge.service import KnowledgeService
from plc_compliance.knowledge.vectorstore import ChromaVectorStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="knowledge_sources")
    parser.add_argument("--database", default="knowledge_db/chroma")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    args = parser.parse_args()

    source_root = Path(args.sources)
    database_root = Path(args.database)
    database_root.mkdir(parents=True, exist_ok=True)
    service = KnowledgeService(
        embeddings=FastEmbedProvider(model_name=args.model),
        vector_store=ChromaVectorStore(path=str(database_root)),
    )
    imported = KnowledgeSourceImporter(service=service).import_directory(source_root)
    chunks = [chunk for items in imported.values() for chunk in items]
    candidates = CandidateRuleExtractor().extract(chunks)
    rule_path = database_root / "baseline_candidates.json"
    rule_path.write_text(
        json.dumps([rule.model_dump() for rule in candidates], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_path = database_root / "index_manifest.json"
    manifest_path.write_text(json.dumps({
        "embedding_model": args.model,
        "embedding_dimensions": service.embeddings.dimensions,
        "documents": len(imported),
        "chunks": len(chunks),
        "candidate_rules": len(candidates),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_directory": str(source_root.resolve()),
        "rule_status": "candidate_requires_expert_review",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"文档数={len(imported)}，文本片段数={len(chunks)}，候选规则数={len(candidates)}")
    print(f"向量数据库={database_root.resolve()}")
    print(f"候选规则文件={rule_path.resolve()}")
    print(f"索引清单={manifest_path.resolve()}")


if __name__ == "__main__":
    main()
