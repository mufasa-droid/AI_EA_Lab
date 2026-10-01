"""
AI EA Lab - Auditor Schemas & Data Models (Phase 10)

Defines structured schemas, ID generators, and validators for:
1. Experiment Audits (AUD-XXXX)
2. Evaluation dimensions (identity, provenance, integrity, compliance, dataset, etc.)
3. Evidence grading (fact vs inference vs risk)
4. Safety invariants enforcement (no rankings, no scores, no winners)
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AUDIT_ID_PATTERN = re.compile(r"^AUD-(\d{4,})$", re.IGNORECASE)
EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-(\d{4,})$", re.IGNORECASE)
CANDIDATE_ID_PATTERN = re.compile(r"^CAND-(\d{4,})$", re.IGNORECASE)
PLAN_ID_PATTERN = re.compile(r"^PLAN-(\d{4,})$", re.IGNORECASE)
HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-(\d{4,})$", re.IGNORECASE)

# Status constants
STATUS_PASS = "PASS"
STATUS_NEEDS_REVIEW = "NEEDS_REVIEW"
STATUS_INVALID = "INVALID"
ALLOWED_STATUSES = {STATUS_PASS, STATUS_NEEDS_REVIEW, STATUS_INVALID}

# Evidence grades
GRADE_STRONG = "STRONG"
GRADE_ADEQUATE = "ADEQUATE"
GRADE_LIMITED = "LIMITED"
GRADE_INSUFFICIENT = "INSUFFICIENT"
GRADE_UNKNOWN = "UNKNOWN"
ALLOWED_GRADES = {GRADE_STRONG, GRADE_ADEQUATE, GRADE_LIMITED, GRADE_INSUFFICIENT, GRADE_UNKNOWN}

# Compliance constants
COMPLIANCE_COMPLIANT = "COMPLIANT"
COMPLIANCE_PARTIALLY_COMPLIANT = "PARTIALLY_COMPLIANT"
COMPLIANCE_NON_COMPLIANT = "NON_COMPLIANT"
COMPLIANCE_NOT_APPLICABLE = "NOT_APPLICABLE"
COMPLIANCE_UNKNOWN = "UNKNOWN"

# Risk levels
RISK_OBSERVED = "OBSERVED"
RISK_POSSIBLE = "POSSIBLE"
RISK_UNKNOWN = "UNKNOWN"

# Prohibited ranking / optimization keywords
FORBIDDEN_WORDS = {
    "winner",
    "best ea",
    "best experiment",
    "leaderboard",
    "score out of 100",
    "recommend to trade",
    "predicted profitability",
    "optimal strategy",
    "superior performance",
}


def get_next_audit_id(audits_dir: Path) -> str:
    """
    Finds the next sequential audit ID formatted as AUD-XXXX.
    Ensures existing audit records are never overwritten.
    """
    audits_dir = Path(audits_dir)
    audits_dir.mkdir(parents=True, exist_ok=True)
    existing_nums = []

    for item in audits_dir.iterdir():
        # Check files like AUD-0001.json or subdirs like AUD-0001
        stem = item.stem if item.is_file() else item.name
        match = AUDIT_ID_PATTERN.match(stem)
        if match:
            existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums) + 1 if existing_nums else 1
    return f"AUD-{next_num:04d}"


def validate_audit_dict(audit_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates that an audit dictionary conforms to the Phase 10 audit schema.
    Returns (is_valid, list_of_issues).
    """
    issues = []
    if not isinstance(audit_dict, dict):
        return False, ["Audit artifact must be a dictionary."]

    # Required top-level fields
    required_keys = [
        "schema_version",
        "audit_id",
        "audited_at",
        "experiment_id",
        "status",
        "evidence_grade",
        "infrastructure_evidence",
        "trading_performance_evidence",
        "experiment_identity_check",
        "provenance_check",
        "artifact_integrity_check",
        "tester_execution_check",
        "report_consistency_check",
        "plan_compliance_check",
        "change_scope_check",
        "dataset_check",
        "reproducibility_check",
        "overfitting_risks",
        "data_leakage_risks",
        "robustness_concerns",
        "evidence_gaps",
        "observations",
        "interpretations",
        "limitations",
        "follow_up_questions",
    ]

    for key in required_keys:
        if key not in audit_dict:
            issues.append(f"Missing required key '{key}'.")

    # Schema version
    if audit_dict.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {audit_dict.get('schema_version')}.")

    # Audit ID pattern
    aid = audit_dict.get("audit_id", "")
    if not AUDIT_ID_PATTERN.match(str(aid)):
        issues.append(f"Invalid audit_id format: '{aid}'. Expected AUD-XXXX.")

    # Experiment ID pattern
    eid = audit_dict.get("experiment_id", "")
    if not EXPERIMENT_ID_PATTERN.match(str(eid)):
        issues.append(f"Invalid experiment_id format: '{eid}'. Expected EXP-XXXX.")

    # Status
    status = audit_dict.get("status")
    if status not in ALLOWED_STATUSES:
        issues.append(f"Invalid status '{status}'. Must be one of: {sorted(ALLOWED_STATUSES)}.")

    # Evidence grade
    grade = audit_dict.get("evidence_grade")
    if grade not in ALLOWED_GRADES:
        issues.append(f"Invalid evidence_grade '{grade}'. Must be one of: {sorted(ALLOWED_GRADES)}.")

    infra_grade = audit_dict.get("infrastructure_evidence")
    if infra_grade not in ALLOWED_GRADES:
        issues.append(f"Invalid infrastructure_evidence '{infra_grade}'. Must be one of: {sorted(ALLOWED_GRADES)}.")

    trading_grade = audit_dict.get("trading_performance_evidence")
    if trading_grade not in ALLOWED_GRADES:
        issues.append(f"Invalid trading_performance_evidence '{trading_grade}'. Must be one of: {sorted(ALLOWED_GRADES)}.")

    # Prohibited rankings / forbidden words check
    serialized = json.dumps(audit_dict).lower()
    for forbidden in FORBIDDEN_WORDS:
        if forbidden in serialized:
            issues.append(f"Prohibited ranking/optimization term found in audit: '{forbidden}'.")

    return len(issues) == 0, issues
