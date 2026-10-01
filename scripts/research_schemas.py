"""
Research Schemas & Data Models

Defines structured schemas and validators for:
1. Research Hypotheses (HYP-XXXX)
2. Experiment Specifications / Plans (PLAN-XXXX)

Enforces clear separation between facts, inferences, hypotheses, and expected observations.
Enforces baseline references and controlled testing rules.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-(\d{4,})$", re.IGNORECASE)
PLAN_ID_PATTERN = re.compile(r"^PLAN-(\d{4,})$", re.IGNORECASE)


def get_next_hypothesis_id(hypotheses_dir: Path) -> str:
    """
    Finds the next sequential hypothesis ID formatted as HYP-XXXX.
    """
    hypotheses_dir = Path(hypotheses_dir)
    hypotheses_dir.mkdir(parents=True, exist_ok=True)
    existing_nums = []

    for file in hypotheses_dir.glob("*.json"):
        match = HYPOTHESIS_ID_PATTERN.match(file.stem)
        if match:
            existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums) + 1 if existing_nums else 1
    return f"HYP-{next_num:04d}"


def get_next_plan_id(plans_dir: Path) -> str:
    """
    Finds the next sequential experiment plan ID formatted as PLAN-XXXX.
    """
    plans_dir = Path(plans_dir)
    plans_dir.mkdir(parents=True, exist_ok=True)
    existing_nums = []

    for file in plans_dir.glob("*.json"):
        match = PLAN_ID_PATTERN.match(file.stem)
        if match:
            existing_nums.append(int(match.group(1)))

    next_num = max(existing_nums) + 1 if existing_nums else 1
    return f"PLAN-{next_num:04d}"


def validate_hypothesis_dict(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates a hypothesis dictionary against the hypothesis schema.
    Returns (is_valid, list_of_issues).
    """
    issues: List[str] = []

    if not isinstance(data, dict):
        return False, ["Root hypothesis must be a JSON object."]

    # 1. Schema version
    if data.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {data.get('schema_version')}")

    # 2. Hypothesis ID format
    hyp_id = data.get("hypothesis_id")
    if not hyp_id or not HYPOTHESIS_ID_PATTERN.match(str(hyp_id)):
        issues.append(f"Invalid or missing hypothesis_id: '{hyp_id}'. Expected format HYP-XXXX.")

    # 3. Core textual fields
    for field in ["title", "research_question", "hypothesis"]:
        val = data.get(field)
        if not val or not str(val).strip():
            issues.append(f"Missing required field '{field}'.")

    # 4. Basis validation (Fact vs Inference separation)
    basis = data.get("basis")
    if not isinstance(basis, dict):
        issues.append("Missing or invalid 'basis' dictionary.")
    else:
        hist_exps = basis.get("historical_experiments")
        if not isinstance(hist_exps, list) or len(hist_exps) == 0:
            issues.append("Basis must cite at least one historical experiment in 'historical_experiments'.")
        facts = basis.get("facts")
        if not isinstance(facts, list) or len(facts) == 0:
            issues.append("Basis must specify at least one observed fact in 'facts'.")
        inferences = basis.get("inferences")
        if not isinstance(inferences, list):
            issues.append("Basis must include an 'inferences' list.")

    # 5. Variables
    ind_vars = data.get("independent_variables")
    if not isinstance(ind_vars, list) or len(ind_vars) == 0:
        issues.append("Hypothesis must declare at least one independent variable.")
    else:
        for idx, var in enumerate(ind_vars):
            if not isinstance(var, dict) or not var.get("name"):
                issues.append(f"Independent variable at index {idx} missing 'name'.")

    dep_vars = data.get("dependent_variables")
    if not isinstance(dep_vars, list) or len(dep_vars) == 0:
        issues.append("Hypothesis must declare at least one dependent variable.")

    ctrl_vars = data.get("control_variables")
    if not isinstance(ctrl_vars, list):
        issues.append("Hypothesis must declare 'control_variables' list.")

    # 6. Expected observations & falsification conditions
    exp_obs = data.get("expected_observations")
    if not isinstance(exp_obs, list) or len(exp_obs) == 0:
        issues.append("Hypothesis must define at least one expected observation.")

    fals_cond = data.get("falsification_conditions")
    if not isinstance(fals_cond, list) or len(fals_cond) == 0:
        issues.append("Hypothesis must define at least one falsification condition.")

    # 7. Dataset specification
    dataset = data.get("dataset")
    if not isinstance(dataset, dict):
        issues.append("Hypothesis must include a 'dataset' specification object.")
    else:
        if "type" not in dataset:
            issues.append("Dataset specification missing 'type'.")

    # 8. Status
    status = data.get("status")
    allowed_statuses = {"proposed", "approved", "rejected", "tested"}
    if status not in allowed_statuses:
        issues.append(f"Invalid hypothesis status: '{status}'. Allowed: {allowed_statuses}")

    return len(issues) == 0, issues


def validate_experiment_plan_dict(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validates an experiment plan dictionary against the experiment specification schema.
    Returns (is_valid, list_of_issues).
    """
    issues: List[str] = []

    if not isinstance(data, dict):
        return False, ["Root experiment plan must be a JSON object."]

    # 1. Schema version
    if data.get("schema_version") != 1:
        issues.append(f"Invalid schema_version: expected 1, got {data.get('schema_version')}")

    # 2. Plan ID format
    plan_id = data.get("experiment_plan_id")
    if not plan_id or not PLAN_ID_PATTERN.match(str(plan_id)):
        issues.append(f"Invalid or missing experiment_plan_id: '{plan_id}'. Expected format PLAN-XXXX.")

    # 3. Hypothesis reference
    hyp_id = data.get("hypothesis_id")
    if not hyp_id or not HYPOTHESIS_ID_PATTERN.match(str(hyp_id)):
        issues.append(f"Invalid or missing hypothesis_id: '{hyp_id}'.")

    # 4. Core textual fields
    for field in ["research_question", "objective"]:
        val = data.get(field)
        if not val or not str(val).strip():
            issues.append(f"Missing required field '{field}'.")

    # 5. Baseline reference
    baseline = data.get("baseline")
    if not isinstance(baseline, dict) or not baseline.get("experiment_id"):
        issues.append("Experiment plan must specify a valid 'baseline' object with 'experiment_id'.")
    else:
        bid = baseline.get("experiment_id")
        if not re.match(r"^EXP-\d{4,}$", str(bid), re.IGNORECASE):
            issues.append(f"Baseline experiment_id '{bid}' must match pattern EXP-XXXX.")

    # 6. Changes under test
    changes = data.get("changes_under_test")
    if not isinstance(changes, list) or len(changes) == 0:
        issues.append("Plan must specify at least one change under test in 'changes_under_test'.")
    else:
        for idx, chg in enumerate(changes):
            if not isinstance(chg, dict) or not chg.get("variable"):
                issues.append(f"Change at index {idx} missing 'variable' name.")

    # 7. Parameters
    params = data.get("parameters")
    if not isinstance(params, dict):
        issues.append("Plan must specify 'parameters' dictionary.")

    # 8. Dataset
    dataset = data.get("dataset")
    if not isinstance(dataset, dict):
        issues.append("Plan must include a 'dataset' object.")

    # 9. Observations & Falsification
    obs = data.get("observations")
    if not isinstance(obs, list) or len(obs) == 0:
        issues.append("Plan must specify measurable 'observations'.")

    exp_obs = data.get("expected_observations")
    if not isinstance(exp_obs, list) or len(exp_obs) == 0:
        issues.append("Plan must specify 'expected_observations'.")

    fals_cond = data.get("falsification_conditions")
    if not isinstance(fals_cond, list) or len(fals_cond) == 0:
        issues.append("Plan must specify 'falsification_conditions'.")

    # 10. Human review & Status
    if data.get("human_review_required") is not True:
        issues.append("Experiment plan must enforce 'human_review_required': true.")

    status = data.get("status")
    allowed_statuses = {"planned", "approved", "rejected", "executed"}
    if status not in allowed_statuses:
        issues.append(f"Invalid plan status: '{status}'. Allowed: {allowed_statuses}")

    return len(issues) == 0, issues
