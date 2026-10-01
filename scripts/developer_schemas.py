"""
Developer Schemas & Data Models

Defines structured schemas, ID generators, and validators for:
1. Candidate metadata (CAND-XXXX)
2. Change manifests
3. Feasibility analyses
4. Human approval state enforcement
5. Static code change validation
"""
import difflib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CANDIDATE_ID_PATTERN = re.compile(r"^CAND-(\d{4,})$", re.IGNORECASE)
PLAN_ID_PATTERN = re.compile(r"^PLAN-(\d{4,})$", re.IGNORECASE)
EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-(\d{4,})$", re.IGNORECASE)


def get_next_candidate_id(candidates_dir: Path) -> str:
    """
    Finds the next sequential candidate ID formatted as CAND-XXXX.
    Never reuses existing IDs.
    """
    candidates_dir = Path(candidates_dir)
    candidates_dir.mkdir(parents=True, exist_ok=True)
    existing_nums = []

    for item in candidates_dir.iterdir():
        if item.is_dir():
            match = CANDIDATE_ID_PATTERN.match(item.name)
            if match:
                existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums) + 1 if existing_nums else 1
    return f"CAND-{next_num:04d}"


def check_plan_approval(plan: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Validates explicit human approval on an experiment plan.
    Human approval CANNOT be inferred from 'human_review_required: true'
    or from plan existence or CLI invocation.
    
    Returns (is_approved, reason, approval_block).
    """
    if not isinstance(plan, dict):
        return False, "Plan is not a valid JSON dictionary.", {}

    approval = plan.get("approval")
    if not approval or not isinstance(approval, dict):
        return (
            False,
            "Approval missing: Plan does not contain an explicit 'approval' block. "
            "Human approval is required before candidate development.",
            {"status": "pending"}
        )

    status = str(approval.get("status", "")).strip().lower()
    if status == "approved":
        return True, "Human approval verified.", approval
    elif status == "pending":
        return (
            False,
            "Approval pending: Plan is awaiting explicit human approval.",
            approval
        )
    elif status == "rejected":
        return (
            False,
            f"Approval rejected: Plan was rejected by human reviewer. Reason: {approval.get('reason', 'None specified')}",
            approval
        )
    else:
        return (
            False,
            f"Invalid approval status '{status}'. Allowed statuses: 'pending', 'approved', 'rejected'.",
            approval
        )


def set_plan_approval(
    plan_path: Path,
    status: str,
    approved_by: str = "human_reviewer",
    note: str = "",
) -> Dict[str, Any]:
    """
    Explicitly updates the human approval state of a plan on disk.
    Allowed statuses: 'approved', 'pending', 'rejected'.
    """
    plan_path = Path(plan_path)
    if not plan_path.is_file():
        raise FileNotFoundError(f"Plan file not found: {plan_path}")

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    status_clean = status.strip().lower()
    if status_clean not in {"approved", "pending", "rejected"}:
        raise ValueError(f"Invalid status: '{status}'. Allowed: 'approved', 'pending', 'rejected'.")

    plan["approval"] = {
        "status": status_clean,
        "reviewed_by": approved_by,
        "reviewed_at": datetime.now().astimezone().isoformat(),
        "note": note,
    }

    if status_clean == "approved":
        plan["status"] = "approved"
    elif status_clean == "rejected":
        plan["status"] = "rejected"
    elif status_clean == "pending":
        plan["status"] = "planned"

    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2)

    return plan


def validate_candidate_metadata(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates candidate metadata against schema rules.
    """
    issues: List[str] = []
    if not isinstance(data, dict):
        return False, ["Candidate metadata must be a JSON dictionary."]

    if data.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {data.get('schema_version')}")

    cid = data.get("candidate_id")
    if not cid or not CANDIDATE_ID_PATTERN.match(str(cid)):
        issues.append(f"Invalid or missing candidate_id: '{cid}'. Expected format CAND-XXXX.")

    pid = data.get("plan_id")
    if not pid or not PLAN_ID_PATTERN.match(str(pid)):
        issues.append(f"Invalid or missing plan_id: '{pid}'. Expected format PLAN-XXXX.")

    bid = data.get("baseline_experiment")
    if not bid or not EXPERIMENT_ID_PATTERN.match(str(bid)):
        issues.append(f"Invalid or missing baseline_experiment: '{bid}'. Expected format EXP-XXXX.")

    for field in ["ea", "created_at", "source_before_sha256", "source_after_sha256", "status"]:
        if not data.get(field):
            issues.append(f"Missing required metadata field '{field}'.")

    return len(issues) == 0, issues


def validate_change_manifest(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates change manifest dictionary.
    """
    issues: List[str] = []
    if not isinstance(data, dict):
        return False, ["Change manifest must be a JSON dictionary."]

    if data.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {data.get('schema_version')}")

    cid = data.get("candidate_id")
    if not cid or not CANDIDATE_ID_PATTERN.match(str(cid)):
        issues.append(f"Invalid candidate_id: '{cid}'.")

    if not isinstance(data.get("changes"), list):
        issues.append("Missing or invalid 'changes' list.")

    if not isinstance(data.get("unauthorized_changes"), list):
        issues.append("Missing or invalid 'unauthorized_changes' list.")

    return len(issues) == 0, issues


def validate_feasibility_dict(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates feasibility analysis dictionary.
    """
    issues: List[str] = []
    if not isinstance(data, dict):
        return False, ["Feasibility analysis must be a JSON dictionary."]

    if data.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {data.get('schema_version')}")

    if "feasible" not in data or not isinstance(data["feasible"], bool):
        issues.append("Missing or invalid boolean 'feasible' field.")

    status = data.get("status")
    allowed = {"pass", "feasible", "blocked", "requires_plan_revision"}
    if status not in allowed:
        issues.append(f"Invalid feasibility status '{status}'. Allowed: {allowed}")

    if not data.get("reason") and not data.get("feasible"):
        issues.append("Infeasible analysis must include a descriptive 'reason'.")

    return len(issues) == 0, issues


def validate_static_changes(
    source_before: str,
    source_after: str,
    authorized_changes: List[Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """
    Performs static verification that ONLY authorized input parameters were modified.
    Ensures:
    - No unauthorized input variables changed.
    - No function definitions (OnInit, OnDeinit, OnTick, etc.) were altered.
    - No preprocessor directives (#include, #property, #define) were altered.
    - No global variables or trade logic was introduced/altered.
    
    Returns (is_valid, authorized_applied, unauthorized_detected).
    """
    unauthorized: List[str] = []
    applied: List[Dict[str, Any]] = []

    lines_before = source_before.splitlines()
    lines_after = source_after.splitlines()

    # Create map of authorized changes {var_name: target_value}
    auth_map = {c["variable"]: str(c["target_value"]) for c in authorized_changes if "variable" in c}

    diff = list(difflib.unified_diff(lines_before, lines_after, lineterm=""))
    if not diff:
        return True, [], []

    # Regex for input variable lines
    # e.g.: input int FastMAPeriod = 10;
    input_pattern = re.compile(
        r"^\s*input\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s*=\s*([^;]+);",
        re.IGNORECASE
    )

    removed_lines = [line[1:].strip() for line in diff if line.startswith("-") and not line.startswith("---")]
    added_lines = [line[1:].strip() for line in diff if line.startswith("+") and not line.startswith("+++")]

    # Check removed and added lines
    for line in removed_lines:
        match = input_pattern.match(line)
        if match:
            var_name = match.group(2)
            if var_name not in auth_map:
                unauthorized.append(f"Unauthorized removal/modification of input parameter '{var_name}': '{line}'")
        else:
            unauthorized.append(f"Unauthorized modification of non-input code: '{line}'")

    for line in added_lines:
        match = input_pattern.match(line)
        if match:
            var_type = match.group(1)
            var_name = match.group(2)
            var_val = match.group(3).strip()
            if var_name not in auth_map:
                unauthorized.append(f"Unauthorized addition/modification of input parameter '{var_name}': '{line}'")
            else:
                expected_val = auth_map[var_name]
                # Compare value representation
                if var_val != expected_val:
                    unauthorized.append(
                        f"Parameter '{var_name}' set to '{var_val}', but approved plan authorized '{expected_val}'"
                    )
                else:
                    applied.append({
                        "type": "input_default_change",
                        "parameter": var_name,
                        "type_declared": var_type,
                        "after": var_val,
                    })
        else:
            unauthorized.append(f"Unauthorized insertion of non-input code: '{line}'")

    is_valid = len(unauthorized) == 0
    return is_valid, applied, unauthorized
