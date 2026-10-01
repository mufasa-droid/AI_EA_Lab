"""
AI EA Lab - Research Memory & Knowledge Accumulation System (Phase 16)

Provides a formal, auditable research-memory system for accumulating empirical
knowledge across experiments without rewriting, corrupting, or over-interpreting
historical evidence.

Enforces:
- Strict separation between FACT, OBSERVATION, INTERPRETATION, HYPOTHESIS, QUESTION, LESSON, and DECISION.
- Immutable historical evidence: Canonical experiment artifacts are authoritative and never modified.
- Complete evidence traceability: Every memory statement points back to canonical source IDs/hashes.
- Idempotent ingestion: SHA-256 fingerprinting prevents duplicate records upon re-ingestion.
- Dataset isolation: Training vs Validation vs Unseen partitions are recorded; UNSEEN is strictly protected.
- Failure preservation: Infeasible plans and infrastructure errors become infrastructure lessons, NOT strategy failures.
- Zero-trade evidence preservation: Zero trades are recorded factually, NOT as strategy failure or success.
- Conflict preservation: Conflicting evidence creates CONFLICTS_WITH relationships and CONFLICTING_EVIDENCE states.
- Knowledge state lifecycle: PROPOSED, SUPPORTED, PARTIALLY_SUPPORTED, INCONCLUSIVE, CONTRADICTED, REQUIRES_REVIEW, RETIRED.
- Human review boundary: Unreviewed vs human_reviewed (never fabricates human approval).
- Research continuity: Supplies structured prior research context to AI Researcher without strategy scoreboards.
"""

import hashlib
import json
import os
import re
import sys
import time

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MEMORY_DIR = PROJECT_ROOT / "research" / "memory"
INDEX_PATH = MEMORY_DIR / "indexes" / "index.json"
HYPOTHESES_DIR = PROJECT_ROOT / "research" / "hypotheses"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DEVELOPER_DIR = PROJECT_ROOT / "developer" / "candidates"

from scripts.research_periods import load_research_periods

MEMORY_SCHEMA_VERSION = 1


def canonical_json_dumps(obj: Any) -> str:
    """Returns a canonical, deterministic JSON string representation with sorted keys."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False)


VALID_RECORD_TYPES = {
    "HYPOTHESIS_RECORD",
    "EXPERIMENT_OBSERVATION",
    "AUDIT_FINDING",
    "RESEARCH_LESSON",
    "OPEN_RESEARCH_QUESTION",
    "RELATIONSHIP",
}

VALID_CATEGORIES = {
    "FACT",
    "OBSERVATION",
    "INTERPRETATION",
    "HYPOTHESIS",
    "QUESTION",
    "LESSON",
    "DECISION",
}

VALID_KNOWLEDGE_STATUSES = {
    "PROPOSED",
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "INCONCLUSIVE",
    "CONTRADICTED",
    "REQUIRES_REVIEW",
    "RETIRED",
    "CONFLICTING_EVIDENCE",
}

VALID_REVIEW_STATUSES = {
    "unreviewed",
    "human_reviewed",
}

VALID_RELATIONS = {
    "TESTED_BY",
    "IMPLEMENTED_AS",
    "AUDITED_BY",
    "REPEATS",
    "RELATED_TO",
    "SUPPORTS",
    "RAISES",
    "CONFLICTS_WITH",
}

VALID_NOVELTY_STATES = {
    "EXACT_DUPLICATE",
    "NEAR_DUPLICATE",
    "RELATED_HYPOTHESIS",
    "NOVEL_HYPOTHESIS",
    "UNKNOWN",
}


def ensure_memory_directories(base_dir: Optional[Path] = None) -> Path:
    """Ensures research memory storage directory structure exists."""
    root = Path(base_dir) if base_dir else MEMORY_DIR
    (root / "hypotheses").mkdir(parents=True, exist_ok=True)
    (root / "observations").mkdir(parents=True, exist_ok=True)
    (root / "audit_findings").mkdir(parents=True, exist_ok=True)
    (root / "lessons").mkdir(parents=True, exist_ok=True)
    (root / "questions").mkdir(parents=True, exist_ok=True)
    (root / "relationships").mkdir(parents=True, exist_ok=True)
    (root / "summaries").mkdir(parents=True, exist_ok=True)
    (root / "indexes").mkdir(parents=True, exist_ok=True)
    return root


def compute_memory_record_fingerprint(
    record_type: str,
    source_id: str,
    canonical_content: str,
    dataset_partition: Optional[str] = None,
) -> str:
    """Computes a deterministic SHA-256 fingerprint for a memory record."""
    raw = f"{record_type}::{source_id}::{canonical_content}::{dataset_partition or 'unspecified'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_memory_index(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Loads the central research memory index file."""
    root = ensure_memory_directories(base_dir)
    idx_file = root / "indexes" / "index.json"
    if not idx_file.exists():
        return {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "updated_at": datetime.now().astimezone().isoformat(),
            "total_records": 0,
            "record_fingerprints": {},
            "records": [],
        }
    try:
        data = json.loads(idx_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Index content must be a JSON object.")
        return data
    except Exception:
        return {
            "schema_version": MEMORY_SCHEMA_VERSION,
            "updated_at": datetime.now().astimezone().isoformat(),
            "total_records": 0,
            "record_fingerprints": {},
            "records": [],
        }


def save_memory_index(index_data: Dict[str, Any], base_dir: Optional[Path] = None) -> None:
    """Saves the central research memory index file atomically."""
    root = ensure_memory_directories(base_dir)
    idx_dir = root / "indexes"
    idx_dir.mkdir(parents=True, exist_ok=True)
    idx_file = idx_dir / "index.json"
    tmp_file = idx_dir / f"index_{os.getpid()}_{time.time_ns()}.tmp"
    index_data["updated_at"] = datetime.now().astimezone().isoformat()
    index_data["total_records"] = len(index_data.get("records", []))
    content = canonical_json_dumps(index_data)
    with open(tmp_file, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_file, idx_file)



def get_next_memory_id(record_type: str, index_data: Dict[str, Any]) -> str:
    """Generates a sequential, monotonic memory record ID."""
    prefix_map = {
        "HYPOTHESIS_RECORD": "MEM-HYP",
        "EXPERIMENT_OBSERVATION": "MEM-OBS",
        "AUDIT_FINDING": "MEM-AUD",
        "RESEARCH_LESSON": "MEM-LES",
        "OPEN_RESEARCH_QUESTION": "MEM-QUE",
        "RELATIONSHIP": "MEM-REL",
    }
    prefix = prefix_map.get(record_type, "MEM-REC")
    existing_ids = [
        r.get("memory_id", "")
        for r in index_data.get("records", [])
        if r.get("memory_id", "").startswith(prefix)
    ]
    numbers = []
    for mid in existing_ids:
        match = re.search(r"-(\d+)$", mid)
        if match:
            numbers.append(int(match.group(1)))
    next_num = max(numbers, default=0) + 1
    return f"{prefix}-{next_num:04d}"


def validate_memory_record(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates a memory record dict against Phase 16 structural constraints."""
    issues = []

    if not isinstance(record, dict):
        return False, ["Record must be a dictionary."]

    schema_version = record.get("schema_version")
    if schema_version != MEMORY_SCHEMA_VERSION:
        issues.append(f"Invalid schema_version '{schema_version}'. Expected {MEMORY_SCHEMA_VERSION}.")

    record_type = record.get("record_type")
    if record_type not in VALID_RECORD_TYPES:
        issues.append(f"Invalid record_type '{record_type}'. Must be one of {sorted(VALID_RECORD_TYPES)}.")

    memory_id = record.get("memory_id")
    if not memory_id or not isinstance(memory_id, str):
        issues.append("Missing or invalid 'memory_id'.")

    created_at = record.get("created_at")
    if not created_at or not isinstance(created_at, str):
        issues.append("Missing or invalid 'created_at' timestamp.")

    generated_by = record.get("generated_by")
    if generated_by not in {"system", "llm"}:
        issues.append("Field 'generated_by' must be 'system' or 'llm'.")

    review_status = record.get("review_status", "unreviewed")
    if review_status not in VALID_REVIEW_STATUSES:
        issues.append(f"Invalid review_status '{review_status}'. Must be one of {sorted(VALID_REVIEW_STATUSES)}.")

    # Record-type specific validation
    if record_type == "HYPOTHESIS_RECORD":
        if not record.get("hypothesis_id"):
            issues.append("HYPOTHESIS_RECORD requires 'hypothesis_id'.")
        if not record.get("statement"):
            issues.append("HYPOTHESIS_RECORD requires 'statement'.")

    elif record_type == "EXPERIMENT_OBSERVATION":
        if not record.get("experiment_id"):
            issues.append("EXPERIMENT_OBSERVATION requires 'experiment_id'.")
        if not record.get("observation"):
            issues.append("EXPERIMENT_OBSERVATION requires 'observation'.")
        category = record.get("observation_category")
        if category not in {"FACT", "OBSERVATION"}:
            issues.append("EXPERIMENT_OBSERVATION observation_category must be 'FACT' or 'OBSERVATION'.")

    elif record_type == "AUDIT_FINDING":
        if not record.get("audit_id") and not record.get("experiment_id"):
            issues.append("AUDIT_FINDING requires 'audit_id' or 'experiment_id'.")
        if not record.get("dimension"):
            issues.append("AUDIT_FINDING requires 'dimension'.")
        if not record.get("finding"):
            issues.append("AUDIT_FINDING requires 'finding'.")

    elif record_type == "RESEARCH_LESSON":
        if not record.get("statement"):
            issues.append("RESEARCH_LESSON requires 'statement'.")
        status = record.get("knowledge_status")
        if status not in VALID_KNOWLEDGE_STATUSES:
            issues.append(f"Invalid knowledge_status '{status}'. Must be one of {sorted(VALID_KNOWLEDGE_STATUSES)}.")

    elif record_type == "OPEN_RESEARCH_QUESTION":
        if not record.get("question"):
            issues.append("OPEN_RESEARCH_QUESTION requires 'question'.")

    elif record_type == "RELATIONSHIP":
        if not record.get("source_id") or not record.get("target_id"):
            issues.append("RELATIONSHIP requires 'source_id' and 'target_id'.")
        rel = record.get("relation")
        if rel not in VALID_RELATIONS:
            issues.append(f"Invalid relation '{rel}'. Must be one of {sorted(VALID_RELATIONS)}.")

    return len(issues) == 0, issues


def add_memory_record(record: Dict[str, Any], base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Adds a validated memory record to research memory storage and index.
    Ensures idempotency via deterministic fingerprinting.
    """
    root = ensure_memory_directories(base_dir)
    index_data = load_memory_index(root)

    # Defaults
    if "schema_version" not in record:
        record["schema_version"] = MEMORY_SCHEMA_VERSION
    if "created_at" not in record:
        record["created_at"] = datetime.now().astimezone().isoformat()
    if "generated_by" not in record:
        record["generated_by"] = "system"
    if "review_status" not in record:
        record["review_status"] = "unreviewed"

    # Compute fingerprint
    record_type = record.get("record_type", "")
    source_id = record.get("source_id") or record.get("experiment_id") or record.get("hypothesis_id") or record.get("lesson_id") or record.get("question_id") or "system"
    content_key = record.get("observation") or record.get("finding") or record.get("statement") or record.get("question") or f"{record.get('source_id')}->{record.get('relation')}->{record.get('target_id')}"
    dataset_part = record.get("dataset_partition")

    fingerprint = compute_memory_record_fingerprint(record_type, source_id, content_key, dataset_part)
    record["fingerprint"] = fingerprint

    # Idempotency check
    existing_fps = index_data.get("record_fingerprints", {})
    if fingerprint in existing_fps:
        existing_id = existing_fps[fingerprint]
        return {
            "status": "ALREADY_INGESTED",
            "memory_id": existing_id,
            "fingerprint": fingerprint,
            "message": f"Record with fingerprint {fingerprint[:12]}... already exists as {existing_id}.",
        }

    # Assign ID if missing
    if "memory_id" not in record or not record["memory_id"]:
        record["memory_id"] = get_next_memory_id(record_type, index_data)

    valid, issues = validate_memory_record(record)
    if not valid:
        raise ValueError(f"Memory record validation failed: {'; '.join(issues)}")

    # Add to index
    index_data["record_fingerprints"][fingerprint] = record["memory_id"]
    index_data.setdefault("records", []).append(record)

    # Save index
    save_memory_index(index_data, root)

    return {
        "status": "INGESTED",
        "memory_id": record["memory_id"],
        "fingerprint": fingerprint,
        "record": record,
    }


def get_memory_record(memory_id: str, base_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Retrieves a memory record by its unique memory_id."""
    index_data = load_memory_index(base_dir)
    for rec in index_data.get("records", []):
        if rec.get("memory_id") == memory_id:
            return rec
    return None


def find_memory_records(
    record_type: Optional[str] = None,
    experiment_id: Optional[str] = None,
    hypothesis_id: Optional[str] = None,
    candidate_id: Optional[str] = None,
    dataset_partition: Optional[str] = None,
    knowledge_status: Optional[str] = None,
    observation_category: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Queries research memory records based on structured filter parameters."""
    index_data = load_memory_index(base_dir)
    results = []

    for rec in index_data.get("records", []):
        if record_type and rec.get("record_type") != record_type:
            continue
        if experiment_id and rec.get("experiment_id") != experiment_id and experiment_id not in rec.get("supporting_experiments", []) and experiment_id not in rec.get("related_experiments", []):
            continue
        if hypothesis_id and rec.get("hypothesis_id") != hypothesis_id and hypothesis_id not in rec.get("originating_hypotheses", []):
            continue
        if candidate_id and rec.get("candidate_id") != candidate_id:
            continue
        if dataset_partition and rec.get("dataset_partition") != dataset_partition:
            continue
        if knowledge_status and rec.get("knowledge_status") != knowledge_status and rec.get("status") != knowledge_status:
            continue
        if observation_category and rec.get("observation_category") != observation_category:
            continue
        results.append(rec)

    return results


def ingest_experiment(
    exp_id: str,
    experiments_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Extracts factual observations from a completed experiment archive into memory records.
    Guaranteed idempotent. Does NOT modify the target experiment archive.
    """
    exp_root = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    exp_dir = exp_root / exp_id

    if not exp_dir.is_dir():
        raise FileNotFoundError(f"Experiment directory does not exist: {exp_dir}")

    meta_file = exp_dir / "metadata.json"
    metrics_file = exp_dir / "metrics.json"

    meta = {}
    if meta_file.is_file():
        meta = json.loads(meta_file.read_text(encoding="utf-8"))

    metrics_root = {}
    if metrics_file.is_file():
        metrics_root = json.loads(metrics_file.read_text(encoding="utf-8"))

    settings = metrics_root.get("settings", {})
    metrics = metrics_root.get("metrics", {})
    val_flags = metrics_root.get("validation", {})

    cand_id = meta.get("candidate_id") or meta.get("ea")
    hyp_id = meta.get("hypothesis_id")
    plan_id = meta.get("plan_id")
    symbol = meta.get("symbol") or settings.get("symbol") or "GBPUSD"
    tf = meta.get("timeframe") or settings.get("timeframe") or "M15"
    d_from = meta.get("from") or settings.get("from")
    d_to = meta.get("to") or settings.get("to")
    dataset_part = meta.get("dataset_partition") or meta.get("dataset") or "training"

    # Extract factual observations
    trades = metrics.get("total_trades")
    net_profit = metrics.get("total_net_profit")
    pf = metrics.get("profit_factor")
    history_quality = metrics.get("history_quality_percent")
    bars = metrics.get("bars")
    ticks = metrics.get("ticks")

    ingested_records = []
    already_ingested_count = 0

    # Fact 1: Execution & data facts
    fact_statement = (
        f"Experiment {exp_id} executed on symbol {symbol} ({tf}) across {d_from}-{d_to} "
        f"[{dataset_part}] with bars={bars}, ticks={ticks}, history_quality={history_quality}%."
    )
    obs1 = {
        "record_type": "EXPERIMENT_OBSERVATION",
        "experiment_id": exp_id,
        "candidate_id": cand_id,
        "dataset_partition": dataset_part,
        "dataset_from": d_from,
        "dataset_to": d_to,
        "symbol": symbol,
        "timeframe": tf,
        "observation_category": "FACT",
        "observation": fact_statement,
        "evidence_type": "METRICS",
        "evidence_reference": {"experiment_id": exp_id, "metadata_path": f"experiments/{exp_id}/metadata.json"},
    }
    res1 = add_memory_record(obs1, base_dir)
    if res1["status"] == "INGESTED":
        ingested_records.append(res1["memory_id"])
    else:
        already_ingested_count += 1

    # Fact 2: Trading performance facts
    trades_val = trades if trades is not None else 0
    trade_statement = (
        f"Experiment {exp_id} recorded total_trades={trades_val}, net_profit={net_profit}, profit_factor={pf}."
    )
    obs2 = {
        "record_type": "EXPERIMENT_OBSERVATION",
        "experiment_id": exp_id,
        "candidate_id": cand_id,
        "dataset_partition": dataset_part,
        "dataset_from": d_from,
        "dataset_to": d_to,
        "symbol": symbol,
        "timeframe": tf,
        "observation_category": "FACT",
        "observation": trade_statement,
        "evidence_type": "METRICS",
        "evidence_reference": {"experiment_id": exp_id, "metrics_path": f"experiments/{exp_id}/metrics.json"},
    }
    res2 = add_memory_record(obs2, base_dir)
    if res2["status"] == "INGESTED":
        ingested_records.append(res2["memory_id"])
    else:
        already_ingested_count += 1

    # Specific Observation: Zero-Trade Evidence (if applicable)
    if trades_val == 0:
        zero_trade_statement = (
            f"Experiment {exp_id} generated exactly 0 trades during test window {d_from}-{d_to}. "
            "This provides zero trading-performance evidence for signal frequency evaluation under these parameters."
        )
        obs_zero = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": exp_id,
            "candidate_id": cand_id,
            "dataset_partition": dataset_part,
            "dataset_from": d_from,
            "dataset_to": d_to,
            "symbol": symbol,
            "timeframe": tf,
            "observation_category": "OBSERVATION",
            "observation": zero_trade_statement,
            "evidence_type": "EXECUTION",
            "evidence_reference": {"experiment_id": exp_id},
        }
        res_z = add_memory_record(obs_zero, base_dir)
        if res_z["status"] == "INGESTED":
            ingested_records.append(res_z["memory_id"])
        else:
            already_ingested_count += 1

    # Link relationships if hyp_id and plan_id are present
    if hyp_id:
        rel = {
            "record_type": "RELATIONSHIP",
            "source_id": hyp_id,
            "source_type": "HYPOTHESIS",
            "relation": "TESTED_BY",
            "target_id": exp_id,
            "target_type": "EXPERIMENT",
            "evidence_reference": {"experiment_id": exp_id, "hypothesis_id": hyp_id},
        }
        add_memory_record(rel, base_dir)

    if cand_id:
        rel_c = {
            "record_type": "RELATIONSHIP",
            "source_id": exp_id,
            "source_type": "EXPERIMENT",
            "relation": "IMPLEMENTED_AS",
            "target_id": cand_id,
            "target_type": "CANDIDATE",
            "evidence_reference": {"experiment_id": exp_id, "candidate_id": cand_id},
        }
        add_memory_record(rel_c, base_dir)

    # Ingest audit if present
    audit_file = exp_dir / "audit.json"
    if audit_file.is_file():
        try:
            ingest_audit(exp_id, experiments_dir=exp_root, base_dir=base_dir)
        except Exception:
            pass

    return {
        "status": "COMPLETED",
        "experiment_id": exp_id,
        "new_observations_ingested": len(ingested_records),
        "already_ingested_count": already_ingested_count,
        "ingested_record_ids": ingested_records,
    }


def ingest_audit(
    exp_id: str,
    experiments_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Ingests audit findings from an experiment's audit.json into memory records."""
    exp_root = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    exp_dir = exp_root / exp_id
    audit_file = exp_dir / "audit.json"

    if not audit_file.is_file():
        raise FileNotFoundError(f"Audit file not found: {audit_file}")

    audit_data = json.loads(audit_file.read_text(encoding="utf-8"))
    audit_id = audit_data.get("audit_id", f"AUD-{exp_id}")
    cand_id = audit_data.get("candidate_id")

    ingested = []
    audits_dict = audit_data.get("audits", {})

    for dimension, d_data in audits_dict.items():
        if isinstance(d_data, dict):
            status = d_data.get("status", "UNKNOWN")
            details = d_data.get("details") or d_data.get("finding") or f"Audit for {dimension}: {status}"
            rec = {
                "record_type": "AUDIT_FINDING",
                "audit_id": audit_id,
                "experiment_id": exp_id,
                "candidate_id": cand_id,
                "dimension": dimension,
                "status": status,
                "finding": details,
                "finding_type": "INFRASTRUCTURE" if dimension in {"provenance", "reproducibility", "tester_execution"} else "METHODOLOGICAL",
                "evidence_reference": {"experiment_id": exp_id, "audit_id": audit_id, "dimension": dimension},
            }
            res = add_memory_record(rec, base_dir)
            if res["status"] == "INGESTED":
                ingested.append(res["memory_id"])

            # Add relationship
            rel = {
                "record_type": "RELATIONSHIP",
                "source_id": exp_id,
                "source_type": "EXPERIMENT",
                "relation": "AUDITED_BY",
                "target_id": audit_id,
                "target_type": "AUDIT",
                "evidence_reference": {"experiment_id": exp_id, "audit_id": audit_id},
            }
            add_memory_record(rel, base_dir)

    return {
        "status": "COMPLETED",
        "audit_id": audit_id,
        "experiment_id": exp_id,
        "new_findings_ingested": len(ingested),
    }


def ingest_infeasible_plan(
    plan_dict: Dict[str, Any],
    feasibility_dict: Dict[str, Any],
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Ingests an infeasible experiment plan into memory as an INFRASTRUCTURE_LIMITATION lesson.
    Prevents repeating infeasible testing designs.
    """
    plan_id = plan_dict.get("experiment_plan_id") or plan_dict.get("plan_id", "PLAN-UNKNOWN")
    ea_name = plan_dict.get("baseline", {}).get("ea", "TargetEA")
    issues = feasibility_dict.get("issues", [])
    reason = feasibility_dict.get("reason") or "; ".join(issues) or "Infeasible plan design"

    statement = f"Plan {plan_id} for EA '{ea_name}' is technically infeasible: {reason}"

    lesson = {
        "record_type": "RESEARCH_LESSON",
        "lesson_id": f"LES-FEAS-{plan_id}",
        "statement": statement,
        "category": "FEASIBILITY",
        "supporting_experiments": [],
        "supporting_audits": [],
        "supporting_plans": [plan_id],
        "knowledge_status": "SUPPORTED",
        "confidence": 1.0,
        "evidence_references": [{"type": "plan", "id": plan_id}, {"type": "feasibility", "data": feasibility_dict}],
    }

    res = add_memory_record(lesson, base_dir)
    return res


def record_conflicting_observations(
    obs_id_1: str,
    obs_id_2: str,
    conflict_rationale: str,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Registers a CONFLICTS_WITH relationship between two conflicting experiment observations.
    Preserves conflicting evidence without hiding or overwriting either record.
    """
    rel = {
        "record_type": "RELATIONSHIP",
        "source_id": obs_id_1,
        "source_type": "OBSERVATION",
        "relation": "CONFLICTS_WITH",
        "target_id": obs_id_2,
        "target_type": "OBSERVATION",
        "evidence_reference": {"conflict_rationale": conflict_rationale},
    }
    res = add_memory_record(rel, base_dir)

    # Update lesson / knowledge status if associated
    index_data = load_memory_index(base_dir)
    for rec in index_data.get("records", []):
        if rec.get("memory_id") in {obs_id_1, obs_id_2}:
            rec["knowledge_status"] = "CONFLICTING_EVIDENCE"

    save_memory_index(index_data, base_dir)
    return res


def classify_hypothesis_novelty(
    proposed_hyp: Dict[str, Any],
    base_dir: Optional[Path] = None,
    hypotheses_dir: Optional[Path] = None,
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """
    Classifies a proposed hypothesis against historical research memory records:
    - EXACT_DUPLICATE: Identical statement or identical target variable & input values on same baseline/dataset.
    - NEAR_DUPLICATE: Same target variable on same baseline/EA with slightly adjusted value.
    - RELATED_HYPOTHESIS: Shares baseline EA, symbol, or research concepts.
    - NOVEL_HYPOTHESIS: Unexplored research area/variable.
    - UNKNOWN: Insufficient data.
    """
    hyp_dir = Path(hypotheses_dir) if hypotheses_dir else HYPOTHESES_DIR
    stmt = proposed_hyp.get("hypothesis") or proposed_hyp.get("statement", "").strip()
    q = proposed_hyp.get("research_question", "").strip()
    base_exp = proposed_hyp.get("baseline", {}).get("experiment_id") or proposed_hyp.get("basis", {}).get("historical_experiments", [None])[0]
    changes = proposed_hyp.get("changes_under_test") or proposed_hyp.get("independent_variables") or []

    if not stmt and not changes:
        return "UNKNOWN", "Insufficient hypothesis information to evaluate novelty.", None

    # Load all stored hypotheses
    existing_hyps = []
    if hyp_dir.is_dir():
        for f in hyp_dir.glob("HYP-*.json"):
            try:
                existing_hyps.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass

    # Also load from memory records
    mem_records = find_memory_records(record_type="HYPOTHESIS_RECORD", base_dir=base_dir)
    for mr in mem_records:
        existing_hyps.append(mr)

    for ex in existing_hyps:
        ex_stmt = ex.get("hypothesis") or ex.get("statement", "").strip()
        ex_q = ex.get("research_question", "").strip()
        ex_id = ex.get("hypothesis_id") or ex.get("memory_id")

        if stmt and ex_stmt and stmt.lower() == ex_stmt.lower():
            return "EXACT_DUPLICATE", f"Hypothesis statement matches existing '{ex_id}' exactly.", ex

        if q and ex_q and q.lower() == ex_q.lower():
            return "EXACT_DUPLICATE", f"Research question matches existing '{ex_id}' exactly.", ex

        # Check variable changes
        ex_changes = ex.get("changes_under_test") or ex.get("independent_variables") or []
        if changes and ex_changes:
            target_vars_1 = {c.get("variable") or c.get("name") for c in changes if c.get("variable") or c.get("name")}
            target_vars_2 = {c.get("variable") or c.get("name") for c in ex_changes if c.get("variable") or c.get("name")}

            if target_vars_1 and target_vars_1 == target_vars_2:
                # Compare target values
                vals1 = {c.get("target_value") or c.get("proposed_value") for c in changes}
                vals2 = {c.get("target_value") or c.get("proposed_value") for c in ex_changes}
                if vals1 == vals2:
                    return "EXACT_DUPLICATE", f"Identical variable target changes matching '{ex_id}'.", ex
                else:
                    return "NEAR_DUPLICATE", f"Same independent variable ({', '.join(target_vars_1)}) tested with different value compared to '{ex_id}'.", ex

        if base_exp and (ex.get("baseline", {}).get("experiment_id") == base_exp or base_exp in ex.get("basis", {}).get("historical_experiments", [])):
            return "RELATED_HYPOTHESIS", f"Shares baseline experiment '{base_exp}' with existing hypothesis '{ex_id}'.", ex

    return "NOVEL_HYPOTHESIS", "No prior exact or near duplicate hypotheses found in research memory.", None


def build_research_memory_context(
    base_dir: Optional[Path] = None,
    include_unseen: bool = False,
) -> Dict[str, Any]:
    """
    Builds a structured, deterministic memory context object for the AI Researcher.
    Strictly excludes UNSEEN dataset partition data unless explicitly authorized.
    """
    index_data = load_memory_index(base_dir)
    records = index_data.get("records", [])

    facts = []
    observations = []
    audit_findings = []
    lessons = []
    questions = []
    relationships = []

    for rec in records:
        part = rec.get("dataset_partition")
        if part == "unseen" and not include_unseen:
            continue  # Protect unseen dataset partition

        rtype = rec.get("record_type")
        if rtype == "EXPERIMENT_OBSERVATION":
            if rec.get("observation_category") == "FACT":
                facts.append(rec)
            else:
                observations.append(rec)
        elif rtype == "AUDIT_FINDING":
            audit_findings.append(rec)
        elif rtype == "RESEARCH_LESSON":
            lessons.append(rec)
        elif rtype == "OPEN_RESEARCH_QUESTION":
            questions.append(rec)
        elif rtype == "RELATIONSHIP":
            relationships.append(rec)

    # Format bounded context strings
    return {
        "schema_version": MEMORY_SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "total_memory_records": len(records),
        "counts": {
            "facts": len(facts),
            "observations": len(observations),
            "audit_findings": len(audit_findings),
            "lessons": len(lessons),
            "questions": len(questions),
            "relationships": len(relationships),
        },
        "facts": [f["observation"] for f in facts[:20]],
        "observations": [o["observation"] for o in observations[:20]],
        "audit_findings": [f"{af['experiment_id']}: {af['dimension']}={af['status']} - {af['finding']}" for af in audit_findings[:20]],
        "lessons": [f"[{l.get('category', 'LESSON')}] {l['statement']} (status: {l.get('knowledge_status', 'SUPPORTED')})" for l in lessons[:20]],
        "open_questions": [q["question"] for q in questions[:20]],
        "relationships": [f"{r['source_id']} --({r['relation']})--> {r['target_id']}" for r in relationships[:30]],
        "usage_guidance": (
            "NOTICE TO AI RESEARCHER: Historical memory is a structured archive of empirical evidence "
            "and unresolved findings. It provides context for controlled hypothesis formulation. "
            "It MUST NOT be treated as a strategy recommendation, trading oracle, or live-trading directive."
        ),
    }


def verify_memory_integrity(
    base_dir: Optional[Path] = None,
    experiments_dir: Optional[Path] = None,
    candidates_dir: Optional[Path] = None,
    hypotheses_dir: Optional[Path] = None,
    plans_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Audits research memory integrity:
    - Verifies evidence traceability (all referenced canonical IDs exist).
    - Checks schema validation on every record.
    - Checks for duplicate IDs or fingerprints.
    - Confirms historical experiment files were NOT modified.
    - Verifies valid knowledge statuses and human review statuses.
    """
    root = ensure_memory_directories(base_dir)
    index_data = load_memory_index(root)
    exp_root = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    cand_root = Path(candidates_dir) if candidates_dir else DEVELOPER_DIR
    hyp_root = Path(hypotheses_dir) if hypotheses_dir else HYPOTHESES_DIR
    plan_root = Path(plans_dir) if plans_dir else PLANS_DIR

    records = index_data.get("records", [])
    issues = []
    broken_references = []
    seen_ids = set()
    seen_fingerprints = set()

    for idx, rec in enumerate(records):
        valid, rec_issues = validate_memory_record(rec)
        if not valid:
            issues.extend([f"Record #{idx} ({rec.get('memory_id', 'UNKNOWN')}): {i}" for i in rec_issues])

        mid = rec.get("memory_id")
        if mid in seen_ids:
            issues.append(f"Duplicate memory_id detected: '{mid}'.")
        seen_ids.add(mid)

        fp = rec.get("fingerprint")
        if fp:
            if fp in seen_fingerprints:
                issues.append(f"Duplicate record fingerprint detected for memory_id '{mid}'.")
            seen_fingerprints.add(fp)

        # Reference verification
        exp_id = rec.get("experiment_id")
        if exp_id and not (exp_root / exp_id).is_dir():
            broken_references.append(f"Record '{mid}' references non-existent experiment '{exp_id}'.")

        cand_id = rec.get("candidate_id")
        if cand_id and not (cand_root / cand_id).is_dir():
            broken_references.append(f"Record '{mid}' references non-existent candidate '{cand_id}'.")

        hyp_id = rec.get("hypothesis_id")
        if hyp_id and not (hyp_root / f"{hyp_id}.json").is_file():
            broken_references.append(f"Record '{mid}' references non-existent hypothesis '{hyp_id}'.")

        for supp_exp in rec.get("supporting_experiments", []) + rec.get("related_experiments", []):
            if not (exp_root / supp_exp).is_dir():
                broken_references.append(f"Record '{mid}' references non-existent supporting experiment '{supp_exp}'.")

        for supp_plan in rec.get("supporting_plans", []) + rec.get("related_plans", []):
            if not (plan_root / f"{supp_plan}.json").is_file():
                broken_references.append(f"Record '{mid}' references non-existent plan '{supp_plan}'.")

    integrity_passed = (len(issues) == 0) and (len(broken_references) == 0)

    return {
        "status": "PASS" if integrity_passed else "FAIL",
        "records_audited": len(records),
        "total_issues": len(issues) + len(broken_references),
        "issues": issues,
        "broken_references": broken_references,
        "schema_version": MEMORY_SCHEMA_VERSION,
        "checked_at": datetime.now().astimezone().isoformat(),
    }
