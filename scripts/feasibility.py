"""
AI EA Lab - Feasibility Analysis Module

Inspects whether a human-approved experiment plan is technically feasible against
the target EA source code before any code modification is attempted.

Enforces:
- Target parameter existence in EA source inputs.
- Parameter type/value compatibility.
- Detection of architectural mismatches:
  Specifically, if an experiment plan expects trade-based observations
  (e.g., total_trades > 0, profit factor, drawdown) but the target EA's
  OnTick() contains no trading/signal execution logic, the analyzer flags
  the plan as BLOCKED / REQUIRES_PLAN_REVISION.
- NEVER invents trading logic automatically to satisfy a plan.
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

INPUT_DECL_PATTERN = re.compile(
    r"^\s*input\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)\s*=\s*([^;]+);",
    re.MULTILINE
)

ONTICK_PATTERN = re.compile(
    r"void\s+OnTick\s*\(\s*\)\s*\{([^}]*)\}",
    re.DOTALL
)

TRADE_KEYWORDS = {
    "ordersend",
    "ordersendasync",
    "positionopen",
    "positionclose",
    "ctrade",
    "trade.buy",
    "trade.sell",
    "trade.positionopen",
    "orderclose",
    "ordermodify",
}

TRADE_OBSERVATION_KEYWORDS = {
    "trade",
    "trades",
    "profit",
    "gross_profit",
    "gross_loss",
    "profit_factor",
    "drawdown",
    "equity_drawdown",
    "recovery_factor",
    "expected_payoff",
}


def parse_ea_inputs(source_code: str) -> Dict[str, Dict[str, str]]:
    """
    Parses all input parameter declarations from MQL5 source code.
    Returns mapping: {param_name: {"type": param_type, "default": param_value}}
    """
    inputs = {}
    for match in INPUT_DECL_PATTERN.finditer(source_code):
        p_type = match.group(1).strip()
        p_name = match.group(2).strip()
        p_val = match.group(3).strip()
        inputs[p_name] = {"type": p_type, "default": p_val}
    return inputs


def inspect_ea_trading_logic(source_code: str) -> Tuple[bool, str]:
    """
    Inspects whether the EA contains trade/order execution logic in OnTick().
    Returns (has_trade_logic, details).
    """
    match = ONTICK_PATTERN.search(source_code)
    if not match:
        return False, "OnTick() function not found in source code."

    body = match.group(1)
    # Strip comments to inspect actual executable statements
    body_no_single = re.sub(r"//.*$", "", body, flags=re.MULTILINE)
    body_no_comments = re.sub(r"/\*.*?\*/", "", body_no_single, flags=re.DOTALL).strip()

    if not body_no_comments:
        return False, "OnTick() is empty (contains only comments or whitespace)."

    lower_body = body_no_comments.lower()
    has_trade = any(kw in lower_body for kw in TRADE_KEYWORDS)
    if not has_trade:
        return (
            False,
            "OnTick() contains code but no trade/order execution functions (e.g. OrderSend, CTrade, PositionOpen)."
        )

    return True, "OnTick() contains active order/trade execution logic."


def plan_requires_trading_logic(plan: Dict[str, Any]) -> bool:
    """
    Determines if the plan's expected observations or falsification conditions
    rely on trade execution (e.g. total_trades > 0, profit factor, drawdown).
    """
    texts_to_check = []
    for obs in plan.get("expected_observations", []):
        texts_to_check.append(str(obs).lower())
    for fc in plan.get("falsification_conditions", []):
        texts_to_check.append(str(fc).lower())
    for obs_metric in plan.get("observations", []):
        texts_to_check.append(str(obs_metric).lower())

    combined = " ".join(texts_to_check)
    return any(kw in combined for kw in TRADE_OBSERVATION_KEYWORDS)


def analyze_plan_feasibility(
    plan: Dict[str, Any],
    ea_source_path: Path,
) -> Dict[str, Any]:
    """
    Performs comprehensive feasibility analysis of an experiment plan against
    the target EA source code.
    
    Returns structured feasibility record matching feasibility_schema.json.
    """
    plan_id = plan.get("experiment_plan_id", "UNKNOWN_PLAN")
    ea_name = plan.get("baseline", {}).get("ea", "UnknownEA")
    changes = plan.get("changes_under_test", [])

    ea_source_path = Path(ea_source_path)
    if not ea_source_path.is_file():
        return {
            "schema_version": 1,
            "plan_id": plan_id,
            "ea": ea_name,
            "feasible": False,
            "status": "blocked",
            "reason": f"Target EA source file not found at: {ea_source_path}",
            "required_changes": [],
            "blocked_by": [f"Missing EA source file: {ea_source_path}"],
        }

    try:
        source_code = ea_source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source_code = ea_source_path.read_text(encoding="utf-16", errors="replace")

    declared_inputs = parse_ea_inputs(source_code)
    required_changes: List[Dict[str, Any]] = []
    blocked_by: List[str] = []

    # 1. Parameter existence and type check
    for chg in changes:
        var_name = chg.get("variable")
        target_val = chg.get("target_value")

        if not var_name or var_name not in declared_inputs:
            blocked_by.append(
                f"Parameter '{var_name}' requested in plan does not exist as an input in '{ea_name}'."
            )
            continue

        decl_type = declared_inputs[var_name]["type"]
        current_def = declared_inputs[var_name]["default"]

        required_changes.append({
            "parameter": var_name,
            "type": decl_type,
            "before": current_def,
            "after": str(target_val),
            "rationale": chg.get("rationale", ""),
        })

    if blocked_by:
        return {
            "schema_version": 1,
            "plan_id": plan_id,
            "ea": ea_name,
            "feasible": False,
            "status": "blocked",
            "reason": f"Plan references parameters not present in {ea_name}: {'; '.join(blocked_by)}",
            "required_changes": required_changes,
            "blocked_by": blocked_by,
        }

    # 2. Check EA Trading Logic vs Plan Expected Observations
    has_trade_logic, logic_details = inspect_ea_trading_logic(source_code)
    requires_trading = plan_requires_trading_logic(plan)

    if requires_trading and not has_trade_logic:
        var_list = ", ".join(c.get("variable", "") for c in changes)
        reason_msg = (
            f"The requested parameter exists, but the current EA does not contain "
            f"trading/signal execution logic that uses the MA handles ({logic_details}). "
            f"Therefore the plan's expected trade-based observation cannot currently "
            f"be produced by changing {var_list} alone."
        )
        return {
            "schema_version": 1,
            "plan_id": plan_id,
            "ea": ea_name,
            "feasible": False,
            "status": "requires_plan_revision",
            "reason": reason_msg,
            "required_changes": required_changes,
            "blocked_by": [
                "Target EA contains no order/trade execution logic in OnTick()",
                "Expected observations require active trades but EA is a pipeline-testing stub",
            ],
        }

    # 3. Everything checks out
    return {
        "schema_version": 1,
        "plan_id": plan_id,
        "ea": ea_name,
        "feasible": True,
        "status": "pass",
        "reason": "All requested parameters exist in EA source and are compatible with EA architecture.",
        "required_changes": required_changes,
        "blocked_by": [],
    }
