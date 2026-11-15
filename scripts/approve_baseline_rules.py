"""Approve selected candidate rules into a versioned formal rule file."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plc_compliance.rule_registry import BaselineRuleRegistry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="knowledge_db/chroma/baseline_candidates.json")
    parser.add_argument("--output", default="knowledge_db/approved_baseline_rules.json")
    parser.add_argument("--ids", nargs="+", required=True, help="由专家明确批准的候选规则编号")
    args = parser.parse_args()
    candidates = BaselineRuleRegistry.load(args.candidates)
    registry = BaselineRuleRegistry()
    added = registry.approve_candidates(candidates.rules, set(args.ids))
    registry.save(args.output)
    print(f"已批准规则数={len(added)}")
    print(f"正式规则文件={Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
