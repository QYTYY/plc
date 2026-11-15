# PLC Compliance Starter

This directory is the application layer for the industrial-control security
baseline assessment platform. The upstream `libs/deepagents` source remains
unchanged.

## Runtime shape

```text
LangGraph workflow
  ├─ user/project context
  ├─ multimodal intake and case dossier
  ├─ versioned baseline knowledge resolution
  ├─ deterministic rule checks
  ├─ round 1: parallel independent opinions
  ├─ shared-opinion barrier
  ├─ round 2: parallel peer review using round 1 as reference
  ├─ shared-opinion barrier
  ├─ round 3: parallel peer review using round 2 as reference
  └─ judge and human-review decision
```

The application boundary is intentionally split from the harness:

```text
Deep Agents: role agents, tools, context, delegation
LangGraph:   workflow state, barriers, rounds, persistence hooks
This app:    evidence, baselines, rules, reports, feedback
```

## Next integrations

Binary document adapters use the optional packages listed in
`ingestion/requirements.txt`. `RawInput.source` should point to the local PDF,
DOCX, XLSX, XLS, or XLSM file; the extracted facts retain page, paragraph,
table, sheet, and row locations.

1. Replace `PlaceholderRAG` with baseline, vendor, threat, and evidence retrievers.
2. Add OCR, table parsing, command parsing, and evidence-hashing tools.
3. Review candidate rules with `scripts/approve_baseline_rules.py`, then run
   approved constraints through the deterministic `RuleEngine` in `rules.py`.
4. Add a structured judge Agent with evidence and rule citations.
5. Add a LangGraph checkpointer and a review UI before publishing reports.
6. Connect `FeedbackRepository` to a database and promote reviewed changes through versioned releases.

## Module 5: deliberation

`deliberation.py` runs the evidence analyst, baseline expert, and risk analyst
in parallel for three rounds. A round is closed by a barrier before the next
round starts. In rounds two and three, previous opinions are passed as read-only
references; each reviewer must return its own conclusion and may record why it
changed. `make_rule_backed_reviewer` provides an offline smoke-test reviewer;
Deep Agents reviewers can be injected through the same `RoleReviewer` protocol.

## DeepSeek configuration

Install `llm_requirements.txt`, create a `.env` file in the project root and set
`DEEPSEEK_API_KEY`, then construct `create_deepseek_model()` and pass `make_deepseek_reviewer(model)` to each
role. The default model is `deepseek-chat`; override it with `DEEPSEEK_MODEL`.
Keys are read from the environment and are never written to case state or
source files.

The assessment graph now constructs Deep Agents Harness instances for the
Intake Agent and all three review roles. Each role receives its own read-only
RAG tool. Install the runtime dependencies with `llm_requirements.txt`; the
repository copy under `libs/deepagents` remains unchanged.
