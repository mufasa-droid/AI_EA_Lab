# PHASE 16 — RESEARCH MEMORY & KNOWLEDGE ACCUMULATION

## System Overview

Phase 16 establishes a formal **Research Memory & Knowledge Accumulation System** for AI-EA-Lab. This system enables the AI research pipeline to accumulate empirical findings, track open research questions, index technical feasibility limitations, and preserve explicit relationships across iterations without corrupting, rewriting, or over-interpreting historical evidence.

The primary goal of research memory is **RESEARCH CONTINUITY**, not strategy optimization or automated trading.

---

## 1. Research Memory Principles

1. **Canonical Evidence Primacy**: Raw experiment archives (`experiments/EXP-XXXX/`), candidate artifacts (`developer/candidates/CAND-XXXX/`), and audit files (`auditor/audits/AUD-XXXX/`) remain the immutable source of truth. Memory is an indexed representation over evidence. If memory ever conflicts with canonical evidence, canonical evidence wins.
2. **Fact vs Interpretation Separation**: Every statement in memory is strictly classified into `FACT`, `OBSERVATION`, `INTERPRETATION`, `HYPOTHESIS`, `QUESTION`, `LESSON`, or `DECISION`.
3. **Traceability**: Every memory statement points back to canonical source IDs (`experiment_id`, `candidate_id`, `audit_id`, `plan_id`, `hypothesis_id`).
4. **Idempotent Ingestion**: Re-ingesting the same experiment or audit produces `ALREADY_INGESTED` based on SHA-256 content fingerprinting, preventing record duplication.
5. **Dataset Isolation**: Memory explicitly tracks `training`, `validation`, and `unseen` dataset partitions. The `unseen` partition remains strictly protected and is never loaded into general researcher context.
6. **Zero-Trade Factual Recording**: Zero-trade experiments are recorded factually (e.g. `total_trades = 0`), NOT as strategy failure or strategy success.
7. **Conflict Preservation**: Conflicting findings create `CONFLICTS_WITH` relationships and update knowledge state to `CONFLICTING_EVIDENCE`, keeping both observations visible.
8. **Human Oversight**: Derived lessons require explicit human review to move from `unreviewed` to `human_reviewed`. Human approval is never fabricated.

---

## 2. Memory Storage Architecture

Research memory records are maintained in `research/memory/`:

```
research/
└── memory/
    ├── hypotheses/       # Stored HYPOTHESIS_RECORD entries
    ├── observations/     # Stored EXPERIMENT_OBSERVATION entries
    ├── audit_findings/   # Stored AUDIT_FINDING entries
    ├── lessons/          # Stored RESEARCH_LESSON entries
    ├── questions/        # Stored OPEN_RESEARCH_QUESTION entries
    ├── relationships/    # Stored RELATIONSHIP entries
    ├── summaries/        # Derived bounded context summaries
    └── indexes/
        └── index.json    # Central deterministic memory index
```

---

## 3. Explicit Memory Record Schemas

### A. HYPOTHESIS_RECORD (`MEM-HYP-XXXX`)
Tracks proposed and investigated hypotheses:
- `hypothesis_id`: Associated `HYP-XXXX` ID
- `statement`: Testable statement
- `research_question`: Query statement
- `source`: Origin (e.g. `AI Researcher`)
- `related_plans` & `related_experiments`: Lineage links
- `status`: `PROPOSED`, `PLANNED`, `TESTED`, `REJECTED`

### B. EXPERIMENT_OBSERVATION (`MEM-OBS-XXXX`)
Records empirical observations from completed experiments:
- `experiment_id` & `candidate_id`: Lineage links
- `dataset_partition`: `training`, `validation`, `unseen`
- `observation_category`: `FACT` or `OBSERVATION`
- `observation`: Textual observation statement
- `evidence_type`: `METRICS`, `LOGS`, `EXECUTION`

### C. AUDIT_FINDING (`MEM-AUD-XXXX`)
Records evidence evaluation results from AI Auditor:
- `audit_id` & `experiment_id`: Lineage links
- `dimension`: `provenance`, `reproducibility`, `data_integrity`, `tester_execution`, etc.
- `status`: `PASS`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE`
- `finding`: Details of audit check

### D. RESEARCH_LESSON (`MEM-LES-XXXX`)
Records synthesized technical or methodological insights:
- `category`: `FEASIBILITY`, `INFRASTRUCTURE_LIMITATION`, `RESEARCH_INSIGHT`, `METHODOLOGICAL`
- `knowledge_status`: `PROPOSED`, `SUPPORTED`, `PARTIALLY_SUPPORTED`, `INCONCLUSIVE`, `CONTRADICTED`, `REQUIRES_REVIEW`, `RETIRED`
- `supporting_experiments`, `supporting_audits`, `supporting_plans`

### E. OPEN_RESEARCH_QUESTION (`MEM-QUE-XXXX`)
Tracks unexplored queries raised by research:
- `question`: Research question text
- `originating_hypotheses` & `related_experiments`
- `status`: `OPEN`, `INVESTIGATING`, `ANSWERED`, `ABANDONED`

### F. RELATIONSHIP (`MEM-REL-XXXX`)
Records explicit directed relationships between entities:
- `relation`: `TESTED_BY`, `IMPLEMENTED_AS`, `AUDITED_BY`, `REPEATS`, `RELATED_TO`, `SUPPORTS`, `RAISES`, `CONFLICTS_WITH`

---

## 4. Ingestion & Retrieval API (`scripts/memory.py`)

- `ingest_experiment(exp_id)`: Extracts facts, trade metrics, and zero-trade observations idempotently.
- `ingest_audit(exp_id)`: Extracts audit findings into memory records idempotently.
- `ingest_infeasible_plan(plan_dict, feasibility_dict)`: Records infeasible testing designs as `FEASIBILITY` lessons.
- `classify_hypothesis_novelty(proposed_hyp)`: Classifies hypothesis as `EXACT_DUPLICATE`, `NEAR_DUPLICATE`, `RELATED_HYPOTHESIS`, `NOVEL_HYPOTHESIS`, or `UNKNOWN`.
- `build_research_memory_context()`: Assembles bounded, deterministic prior research context for AI Researcher prompts.
- `verify_memory_integrity()`: Audits memory index against canonical files on disk to detect broken references or schema drift.

---

## 5. Operational Safety & Non-Goals

- **NO Live Trading**: Memory does not create trading orders or interface with live broker accounts.
- **NO Strategy Ranking**: Memory does not rank strategies or declare "winning" EAs.
- **NO Optimization Sweeps**: Memory does not perform unconstrained parameter curve-fitting.
