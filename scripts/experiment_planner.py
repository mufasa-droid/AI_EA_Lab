"""
Experiment Planner Module

Translates validated research hypotheses into controlled, actionable Experiment Specifications (PLAN-XXXX).
Enforces:
- Concrete baseline experiment references (e.g. EXP-0002)
- One primary independent variable at a time (generates warning if multiple changes)
- Detection of duplicate parameter sets
- Explicit dataset mapping (respecting unconfigured/configured periods)
- Measurable observations and falsification criteria
- Human approval boundary (status: "planned", human_review_required: true)

Does NOT generate MQL5 code or execute tests.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PLANS_DIR = PROJECT_ROOT / "research" / "plans"

from scripts.research_context import check_duplicate_configuration, get_historical_experiment_details
from scripts.research_schemas import get_next_plan_id, validate_experiment_plan_dict


def create_experiment_plan(
    hypothesis: Dict[str, Any],
    context: Dict[str, Any],
    baseline_id: Optional[str] = None,
    plans_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Constructs an Experiment Plan from a hypothesis and current research context.
    """
    plans_dir = Path(plans_dir) if plans_dir else PLANS_DIR
    plans_dir.mkdir(parents=True, exist_ok=True)

    # 1. Resolve baseline experiment
    target_baseline_id = baseline_id
    if not target_baseline_id:
        target_baseline_id = context.get("project_state", {}).get("latest_experiment_id")
        if not target_baseline_id and context.get("historical_experiments"):
            target_baseline_id = context["historical_experiments"][-1].get("id")

    if not target_baseline_id:
        raise ValueError("Cannot plan experiment without at least one historical experiment to serve as baseline.")

    baseline_exp = get_historical_experiment_details(target_baseline_id)
    if not baseline_exp:
        # Fallback to searching context
        for e in context.get("historical_experiments", []):
            if e.get("id") == target_baseline_id:
                baseline_exp = e
                break

    if not baseline_exp:
        raise FileNotFoundError(f"Baseline experiment '{target_baseline_id}' not found in research context.")

    baseline_inputs = dict(baseline_exp.get("inputs", {}))
    baseline_ea = baseline_exp.get("ea", context.get("project_state", {}).get("ea_name"))
    baseline_symbol = baseline_exp.get("symbol", context.get("project_state", {}).get("symbol"))
    baseline_timeframe = baseline_exp.get("timeframe", context.get("project_state", {}).get("timeframe"))

    # 2. Extract changes under test from hypothesis
    ind_vars = hypothesis.get("independent_variables", [])
    changes_under_test: List[Dict[str, Any]] = []
    target_parameters = dict(baseline_inputs)
    warnings: List[str] = []

    for var in ind_vars:
        v_name = var.get("name")
        proposed_val = var.get("proposed_value")
        current_val = baseline_inputs.get(v_name, var.get("baseline_value"))

        target_parameters[v_name] = proposed_val
        changes_under_test.append({
            "variable": v_name,
            "baseline_value": current_val,
            "target_value": proposed_val,
            "change_type": "parameter_adjustment",
            "rationale": var.get("rationale", ""),
        })

    # 3. Rule: Check multiple simultaneous changes
    if len(changes_under_test) > 1:
        var_names = ", ".join(c["variable"] for c in changes_under_test)
        warnings.append(
            f"Multiple independent variables ({var_names}) are changing simultaneously; "
            "causal attribution may be difficult. Controlled experiments should ideally test one variable at a time."
        )

    # 4. Identify unchanged variables
    unchanged_variables: List[Dict[str, Any]] = []
    for k, v in baseline_inputs.items():
        if k not in [c["variable"] for c in changes_under_test]:
            unchanged_variables.append({"variable": k, "value": v})

    # Also record market environment as unchanged controls
    unchanged_variables.extend([
        {"variable": "ea", "value": baseline_ea},
        {"variable": "symbol", "value": baseline_symbol},
        {"variable": "timeframe", "value": baseline_timeframe},
    ])

    # 5. Rule: Check novelty / duplicate configuration
    dup_id = check_duplicate_configuration(
        proposed_inputs=target_parameters,
        ea=baseline_ea,
        symbol=baseline_symbol,
        timeframe=baseline_timeframe,
        context=context,
    )
    if dup_id:
        warnings.append(
            f"This configuration appears to duplicate existing experiment '{dup_id}' "
            f"with identical inputs ({target_parameters})."
        )

    # 6. Dataset resolution
    hyp_dataset = hypothesis.get("dataset", {})
    periods_cfg = context.get("research_periods", {})

    dataset_plan = {
        "type": hyp_dataset.get("type", "training"),
        "from": hyp_dataset.get("from"),
        "to": hyp_dataset.get("to"),
        "status": periods_cfg.get("status", "unconfigured"),
    }
    if not periods_cfg.get("is_configured", False):
        dataset_plan["note"] = (
            "Research dataset dates are currently unconfigured placeholders. "
            "Dates must be configured in config/research_periods.json before production training."
        )

    # 7. Formulate observations & falsification
    observations = [
        "total_net_profit",
        "profit_factor",
        "equity_drawdown_maximal",
        "total_trades",
        "history_quality_percent",
        "bars",
        "ticks",
    ]

    expected_obs = hypothesis.get("expected_observations", [])
    fals_cond = hypothesis.get("falsification_conditions", [])

    plan_id = get_next_plan_id(plans_dir)
    hyp_id = hypothesis.get("hypothesis_id", "HYP-0000")

    plan = {
        "schema_version": 1,
        "experiment_plan_id": plan_id,
        "hypothesis_id": hyp_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "title": hypothesis.get("title", f"Plan for {hyp_id}"),
        "research_question": hypothesis.get("research_question", ""),
        "objective": (
            f"Test whether changing {', '.join(c['variable'] for c in changes_under_test)} "
            f"relative to baseline {target_baseline_id} produces the expected observations."
        ),
        "baseline": {
            "experiment_id": target_baseline_id,
            "ea": baseline_ea,
            "symbol": baseline_symbol,
            "timeframe": baseline_timeframe,
            "inputs": baseline_inputs,
        },
        "changes_under_test": changes_under_test,
        "unchanged_variables": unchanged_variables,
        "parameters": target_parameters,
        "dataset": dataset_plan,
        "observations": observations,
        "expected_observations": expected_obs,
        "falsification_conditions": fals_cond,
        "warnings": warnings,
        "risks": [
            "Overfitting if parameter is tested excessively across the same period.",
            "Market volatility regime shifts between observation windows.",
        ],
        "human_review_required": True,
        "status": "planned",
    }

    # Validate against schema
    is_valid, issues = validate_experiment_plan_dict(plan)
    if not is_valid:
        raise ValueError(f"Generated experiment plan failed schema validation: {'; '.join(issues)}")

    return plan


def save_experiment_plan(
    plan: Dict[str, Any],
    plans_dir: Optional[Path] = None,
) -> Path:
    """
    Saves the experiment plan to disk under research/plans/PLAN-XXXX.json.
    """
    base_dir = Path(plans_dir) if plans_dir else PLANS_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    plan_id = plan["experiment_plan_id"]
    file_path = base_dir / f"{plan_id}.json"
    file_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return file_path
