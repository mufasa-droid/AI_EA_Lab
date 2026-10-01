"""
AI EA Lab - Research Loop Schemas & State Machine (Phase 11)

Defines data models, state transitions, validation, and ID generation for
the Controlled Autonomous Research Loop:
1. Iteration ID generation (ITER-XXXX).
2. Explicit state machine and valid transition validation.
3. Human approval gate states (PENDING, APPROVED, REJECTED, EXPIRED).
4. Research decision states and safety invariants (no rankings, no scores, no winners).
5. Schema validation for research iteration artifacts.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ITERATION_ID_PATTERN = re.compile(r"^ITER-(\d{4,})$", re.IGNORECASE)
HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-(\d{4,})$", re.IGNORECASE)
PLAN_ID_PATTERN = re.compile(r"^PLAN-(\d{4,})$", re.IGNORECASE)
CANDIDATE_ID_PATTERN = re.compile(r"^CAND-(\d{4,})$", re.IGNORECASE)
EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-(\d{4,})$", re.IGNORECASE)
AUDIT_ID_PATTERN = re.compile(r"^AUD-(\d{4,})$", re.IGNORECASE)
DECISION_ID_PATTERN = re.compile(r"^DEC-(\d{4,})$", re.IGNORECASE)

# --- State Machine States ---
STATE_CREATED = "CREATED"
STATE_RESEARCHING = "RESEARCHING"
STATE_PLANNED = "PLANNED"
STATE_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATE_APPROVED = "APPROVED"
STATE_DEVELOPING = "DEVELOPING"
STATE_CANDIDATE_READY = "CANDIDATE_READY"
STATE_BACKTESTING = "BACKTESTING"
STATE_EXPERIMENT_CREATED = "EXPERIMENT_CREATED"
STATE_AUDITING = "AUDITING"
STATE_AUDITED = "AUDITED"
STATE_DECIDED = "DECIDED"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
STATE_BLOCKED = "BLOCKED"

# Phase 14 Validation States
STATE_VALIDATION_AWAITING_APPROVAL = "VALIDATION_AWAITING_APPROVAL"
STATE_VALIDATION_APPROVED = "VALIDATION_APPROVED"
STATE_VALIDATING = "VALIDATING"
STATE_VALIDATED = "VALIDATED"

ALLOWED_STATES: Set[str] = {
    STATE_CREATED,
    STATE_RESEARCHING,
    STATE_PLANNED,
    STATE_AWAITING_APPROVAL,
    STATE_APPROVED,
    STATE_DEVELOPING,
    STATE_CANDIDATE_READY,
    STATE_BACKTESTING,
    STATE_EXPERIMENT_CREATED,
    STATE_AUDITING,
    STATE_AUDITED,
    STATE_DECIDED,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_BLOCKED,
    STATE_VALIDATION_AWAITING_APPROVAL,
    STATE_VALIDATION_APPROVED,
    STATE_VALIDATING,
    STATE_VALIDATED,
}

# --- State Transition Graph ---
ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    STATE_CREATED: {STATE_RESEARCHING, STATE_PLANNED, STATE_FAILED},
    STATE_RESEARCHING: {STATE_PLANNED, STATE_FAILED},
    STATE_PLANNED: {STATE_AWAITING_APPROVAL, STATE_FAILED},
    STATE_AWAITING_APPROVAL: {STATE_APPROVED, STATE_BLOCKED, STATE_FAILED},
    STATE_APPROVED: {STATE_DEVELOPING, STATE_FAILED},
    STATE_DEVELOPING: {STATE_CANDIDATE_READY, STATE_BLOCKED, STATE_FAILED},
    STATE_CANDIDATE_READY: {STATE_BACKTESTING, STATE_FAILED},
    STATE_BACKTESTING: {STATE_EXPERIMENT_CREATED, STATE_FAILED},
    STATE_EXPERIMENT_CREATED: {STATE_AUDITING, STATE_FAILED},
    STATE_AUDITING: {STATE_AUDITED, STATE_FAILED},
    STATE_AUDITED: {STATE_DECIDED, STATE_VALIDATION_AWAITING_APPROVAL, STATE_FAILED},
    STATE_DECIDED: {STATE_COMPLETED, STATE_VALIDATION_AWAITING_APPROVAL, STATE_FAILED},
    STATE_BLOCKED: {STATE_AWAITING_APPROVAL, STATE_VALIDATION_AWAITING_APPROVAL, STATE_PLANNED, STATE_FAILED},
    STATE_FAILED: set(),  # Terminal
    STATE_COMPLETED: {STATE_VALIDATION_AWAITING_APPROVAL},  # Can transition to validation request if requested
    STATE_VALIDATION_AWAITING_APPROVAL: {STATE_VALIDATION_APPROVED, STATE_BLOCKED, STATE_FAILED},
    STATE_VALIDATION_APPROVED: {STATE_VALIDATING, STATE_FAILED},
    STATE_VALIDATING: {STATE_VALIDATED, STATE_EXPERIMENT_CREATED, STATE_FAILED},
    STATE_VALIDATED: {STATE_AUDITING, STATE_DECIDED, STATE_COMPLETED, STATE_FAILED},
}

# --- Human Approval States ---
APPROVAL_PENDING = "PENDING"
APPROVAL_APPROVED = "APPROVED"
APPROVAL_REJECTED = "REJECTED"
APPROVAL_EXPIRED = "EXPIRED"

ALLOWED_APPROVAL_STATUSES: Set[str] = {
    APPROVAL_PENDING,
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    APPROVAL_EXPIRED,
}

# --- Research Decision Outcomes ---
DECISION_CONTINUE_RESEARCH = "CONTINUE_RESEARCH"
DECISION_REVISE_PLAN = "REVISE_PLAN"
DECISION_REJECT_EXPERIMENT = "REJECT_EXPERIMENT"
DECISION_NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
DECISION_INFRASTRUCTURE_FAILURE = "INFRASTRUCTURE_FAILURE"
DECISION_NEEDS_REPRODUCIBILITY_REVIEW = "NEEDS_REPRODUCIBILITY_REVIEW"
DECISION_RESEARCH_CONFIGURATION_CHANGED = "RESEARCH_CONFIGURATION_CHANGED"
DECISION_CANDIDATE_INTEGRITY_FAILURE = "CANDIDATE_INTEGRITY_FAILURE"
DECISION_DATASET_INTEGRITY_FAILURE = "DATASET_INTEGRITY_FAILURE"

ALLOWED_DECISIONS: Set[str] = {
    DECISION_CONTINUE_RESEARCH,
    DECISION_REVISE_PLAN,
    DECISION_REJECT_EXPERIMENT,
    DECISION_NEEDS_HUMAN_REVIEW,
    DECISION_INFRASTRUCTURE_FAILURE,
    DECISION_NEEDS_REPRODUCIBILITY_REVIEW,
    DECISION_RESEARCH_CONFIGURATION_CHANGED,
    DECISION_CANDIDATE_INTEGRITY_FAILURE,
    DECISION_DATASET_INTEGRITY_FAILURE,
}

# --- Safety Invariant: Prohibited Ranking / Optimization Keywords ---
FORBIDDEN_WORDS: Set[str] = {
    "winner",
    "best ea",
    "best experiment",
    "leaderboard",
    "score out of 100",
    "recommend to trade",
    "predicted profitability",
    "optimal strategy",
    "superior performance",
    "composite score",
}


def get_next_iteration_id(iterations_dir: Path) -> str:
    """
    Finds the next sequential iteration ID formatted as ITER-XXXX.
    Ensures existing iteration directories are never overwritten.
    """
    iterations_dir = Path(iterations_dir)
    iterations_dir.mkdir(parents=True, exist_ok=True)
    existing_nums = []

    for item in iterations_dir.iterdir():
        stem = item.name
        match = ITERATION_ID_PATTERN.match(stem)
        if match:
            existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums) + 1 if existing_nums else 1
    return f"ITER-{next_num:04d}"


def validate_state_transition(current_state: str, next_state: str) -> Tuple[bool, str]:
    """
    Validates whether a state transition from current_state to next_state is permitted.
    Returns (is_valid, reason).
    """
    if current_state not in ALLOWED_STATES:
        return False, f"Unknown current state: '{current_state}'."

    if next_state not in ALLOWED_STATES:
        return False, f"Unknown target state: '{next_state}'."

    allowed_targets = ALLOWED_TRANSITIONS.get(current_state, set())
    if next_state not in allowed_targets:
        return (
            False,
            f"Invalid state transition from '{current_state}' to '{next_state}'. "
            f"Allowed target states: {sorted(allowed_targets) if allowed_targets else 'None (terminal state)'}."
        )

    return True, f"Valid transition: '{current_state}' -> '{next_state}'."


def validate_iteration_dict(iteration_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates that an iteration dictionary conforms to the Phase 11 iteration schema.
    Returns (is_valid, list_of_issues).
    """
    issues = []
    if not isinstance(iteration_dict, dict):
        return False, ["Iteration artifact must be a dictionary."]

    # Required top-level fields
    required_keys = [
        "schema_version",
        "iteration_id",
        "created_at",
        "status",
        "approval_status",
        "approval",
        "hypothesis_id",
        "plan_id",
        "candidate_id",
        "experiment_id",
        "audit_id",
        "decision",
        "provenance",
        "state_history",
    ]

    for key in required_keys:
        if key not in iteration_dict:
            issues.append(f"Missing required key '{key}'.")

    # Schema version
    if iteration_dict.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {iteration_dict.get('schema_version')}.")

    # Iteration ID format
    iter_id = iteration_dict.get("iteration_id", "")
    if not ITERATION_ID_PATTERN.match(str(iter_id)):
        issues.append(f"Invalid iteration_id format: '{iter_id}'. Expected ITER-XXXX.")

    # Status
    status = iteration_dict.get("status")
    if status not in ALLOWED_STATES:
        issues.append(f"Invalid status '{status}'. Must be one of: {sorted(ALLOWED_STATES)}.")

    # Approval Status
    appr_status = iteration_dict.get("approval_status")
    if appr_status not in ALLOWED_APPROVAL_STATUSES:
        issues.append(f"Invalid approval_status '{appr_status}'. Must be one of: {sorted(ALLOWED_APPROVAL_STATUSES)}.")

    # Approval block
    approval = iteration_dict.get("approval")
    if not isinstance(approval, dict):
        issues.append("Iteration 'approval' must be a dictionary.")

    # Provenance
    provenance = iteration_dict.get("provenance")
    if not isinstance(provenance, dict):
        issues.append("Iteration 'provenance' must be a dictionary.")

    # State history
    history = iteration_dict.get("state_history")
    if not isinstance(history, list):
        issues.append("Iteration 'state_history' must be a list.")

    # Prohibited ranking / optimization keywords check
    serialized = json.dumps(iteration_dict).lower()
    for forbidden in FORBIDDEN_WORDS:
        if forbidden in serialized:
            issues.append(f"Prohibited ranking/optimization term found in iteration artifact: '{forbidden}'.")

    return len(issues) == 0, issues
