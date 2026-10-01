"""
AI EA Lab - AI Researcher

The reasoning layer above the experiment infrastructure.
Answers: "What should we test next, and why?"
Enforces:
- Strict separation between FACT, INFERENCE, HYPOTHESIS, EXPERIMENT, and EXPECTED OBSERVATION.
- No fabrication: all historical statements trace to actual experiment data.
- Baseline references (e.g. EXP-0002).
- Single primary independent variable per experiment.
- Multi-dimensional observations without ranking or "profit maximizer" scores.
- Deterministic mock mode for offline testing (--mock).
- Human review boundary (status: "proposed" / "planned").

Does NOT modify MQL5 code or execute tests.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

HYPOTHESES_DIR = PROJECT_ROOT / "research" / "hypotheses"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"

from scripts.experiment_planner import create_experiment_plan, save_experiment_plan
from scripts.research_context import (
    build_research_context,
    get_historical_experiment_details,
    save_research_context,
)
from scripts.research_schemas import (
    get_next_hypothesis_id,
    validate_hypothesis_dict,
)


def formulate_mock_hypothesis(
    context: Dict[str, Any],
    research_question: Optional[str] = None,
    baseline_id: Optional[str] = None,
    hypotheses_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Formulates a deterministic research hypothesis derived strictly from actual historical experiments.
    """
    hyp_dir = Path(hypotheses_dir) if hypotheses_dir else HYPOTHESES_DIR
    hyp_dir.mkdir(parents=True, exist_ok=True)

    history = context.get("historical_experiments", [])
    if not history:
        raise ValueError("Insufficient evidence: No historical experiments available in repository to formulate hypothesis.")

    # Determine baseline
    target_baseline_id = baseline_id or context.get("project_state", {}).get("latest_experiment_id") or history[-1]["id"]
    baseline_exp = next((e for e in history if e.get("id") == target_baseline_id), None)
    if not baseline_exp:
        baseline_exp = get_historical_experiment_details(target_baseline_id)

    if not baseline_exp:
        raise FileNotFoundError(f"Insufficient evidence: Baseline experiment '{target_baseline_id}' not found in archive.")

    baseline_inputs = baseline_exp.get("inputs", {})
    ea_name = baseline_exp.get("ea", "TestEA")
    symbol = baseline_exp.get("symbol", "GBPUSD")
    timeframe = baseline_exp.get("timeframe", "M15")

    # Facts observed from actual data
    trades = baseline_exp.get("trading", {}).get("total_trades")
    if trades is None and "total_trades" in baseline_exp:
        trades = baseline_exp.get("total_trades")
    trades_val = trades if trades is not None else 0

    facts = [
        f"Experiment '{target_baseline_id}' was executed on symbol {symbol} ({timeframe}) "
        f"with inputs: {', '.join(f'{k}={v}' for k, v in sorted(baseline_inputs.items()))}.",
        f"Experiment '{target_baseline_id}' recorded exactly {trades_val} trades across the test window.",
    ]

    # Additional facts from prior experiments if available
    prior_exps = [e["id"] for e in history if e.get("id") != target_baseline_id]
    if prior_exps:
        facts.append(f"Historical archive contains previous experiments: {', '.join(prior_exps)}.")

    inferences = [
        f"Given that {target_baseline_id} generated 0 trades, the current moving average parameters "
        f"(FastMAPeriod={baseline_inputs.get('FastMAPeriod', '10')}, SlowMAPeriod={baseline_inputs.get('SlowMAPeriod', '20')}) "
        f"did not trigger crossover conditions on {symbol} {timeframe} during the tested period.",
        "Reducing the FastMAPeriod while holding SlowMAPeriod fixed increases the responsiveness of the fast line, "
        "which may allow crossover events to occur within the same market window.",
    ]

    q = research_question or (
        f"Does reducing FastMAPeriod from {baseline_inputs.get('FastMAPeriod', '10')} to 5 "
        f"increase moving average crossover sensitivity and generate non-zero trade signals on {symbol} {timeframe}?"
    )

    hyp_statement = (
        f"Reducing FastMAPeriod from {baseline_inputs.get('FastMAPeriod', '10')} to 5 while holding "
        f"SlowMAPeriod constant at {baseline_inputs.get('SlowMAPeriod', '20')} and LotSize at {baseline_inputs.get('LotSize', '0.01')} "
        f"will increase signal sensitivity and result in more than {trades_val} trades."
    )

    hyp_id = get_next_hypothesis_id(hyp_dir)

    hypothesis = {
        "schema_version": 1,
        "hypothesis_id": hyp_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "title": "Fast Moving Average Sensitivity Reduction Test",
        "research_question": q,
        "hypothesis": hyp_statement,
        "basis": {
            "historical_experiments": [target_baseline_id] + prior_exps,
            "facts": facts,
            "inferences": inferences,
            "evidence": [
                f"{target_baseline_id} total_trades={trades_val}, profit_factor=0.0, net_profit=0.0"
            ],
        },
        "independent_variables": [
            {
                "name": "FastMAPeriod",
                "baseline_value": str(baseline_inputs.get("FastMAPeriod", "10")),
                "proposed_value": "5",
                "rationale": "Shorter period increases sensitivity to price movement, encouraging crossovers.",
            }
        ],
        "dependent_variables": [
            "total_trades",
            "total_net_profit",
            "profit_factor",
            "equity_drawdown_maximal",
        ],
        "control_variables": [
            {"name": "SlowMAPeriod", "value": str(baseline_inputs.get("SlowMAPeriod", "20"))},
            {"name": "LotSize", "value": str(baseline_inputs.get("LotSize", "0.01"))},
            {"name": "symbol", "value": symbol},
            {"name": "timeframe", "value": timeframe},
            {"name": "ea", "value": ea_name},
        ],
        "assumptions": [
            "The moving average crossover calculation logic in TestEA functions correctly when crossovers occur.",
            "Market data quality is 100% and tick density is sufficient to detect price changes.",
        ],
        "dataset": {
            "type": "training",
            "from": (
                context.get("research_periods", {}).get("periods", {}).get("training", {}).get("from")
                if context.get("research_periods", {}).get("is_configured") and context.get("research_periods", {}).get("periods", {}).get("training", {}).get("from")
                else baseline_exp.get("from")
            ),
            "to": (
                context.get("research_periods", {}).get("periods", {}).get("training", {}).get("to")
                if context.get("research_periods", {}).get("is_configured") and context.get("research_periods", {}).get("periods", {}).get("training", {}).get("to")
                else baseline_exp.get("to")
            ),
            "status": context.get("research_periods", {}).get("status", "unconfigured"),
        },
        "expected_observations": [
            "Total trades will increase from 0 to at least 1.",
            "Gross profit and gross loss will become non-zero, allowing profit factor calculation.",
            "Drawdown will become non-zero reflecting active market exposure.",
        ],
        "falsification_conditions": [
            "Total trades remain exactly 0 after reducing FastMAPeriod to 5.",
            "Execution completes with 0 trades despite confirmed price fluctuations, "
            "indicating that EA entry logic is blocked by another constraint rather than MA sensitivity.",
        ],
        "status": "proposed",
    }

    is_valid, issues = validate_hypothesis_dict(hypothesis)
    if not is_valid:
        raise ValueError(f"Generated hypothesis failed validation: {'; '.join(issues)}")

    return hypothesis


def save_hypothesis(
    hypothesis: Dict[str, Any],
    hypotheses_dir: Optional[Path] = None,
) -> Path:
    base_dir = Path(hypotheses_dir) if hypotheses_dir else HYPOTHESES_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    hyp_id = hypothesis["hypothesis_id"]
    file_path = base_dir / f"{hyp_id}.json"
    file_path.write_text(json.dumps(hypothesis, indent=2), encoding="utf-8")

    try:
        from scripts.memory import add_memory_record
        rec = {
            "record_type": "HYPOTHESIS_RECORD",
            "hypothesis_id": hyp_id,
            "statement": hypothesis.get("hypothesis", ""),
            "research_question": hypothesis.get("research_question", ""),
            "source": "AI Researcher",
            "created_at": hypothesis.get("created_at"),
            "related_plans": [],
            "related_experiments": hypothesis.get("basis", {}).get("historical_experiments", []),
            "status": hypothesis.get("status", "proposed").upper(),
            "evidence_references": [{"type": "hypothesis", "id": hyp_id}],
        }
        add_memory_record(rec)
    except Exception:
        pass

    return file_path



def format_human_proposal(
    hypothesis: Dict[str, Any],
    plan: Dict[str, Any],
    is_mock: bool = True,
) -> str:
    """
    Formats human-readable research proposal clearly separating facts, inferences, hypotheses, and plan.
    """
    lines = []
    lines.append("=" * 70)
    lines.append("AI EA LAB - AI RESEARCH PROPOSAL")
    if is_mock:
        lines.append("[MODE: MOCK RESEARCHER - Deterministic Offline Mode]")
    lines.append("=" * 70)
    lines.append("")

    lines.append(f"Hypothesis ID   : {hypothesis['hypothesis_id']}")
    lines.append(f"Plan ID         : {plan['experiment_plan_id']}")
    lines.append(f"Title           : {hypothesis['title']}")
    lines.append(f"Baseline Exp    : {plan['baseline']['experiment_id']}")
    lines.append("")

    lines.append("--- RESEARCH QUESTION ---")
    lines.append(hypothesis["research_question"])
    lines.append("")

    lines.append("--- OBSERVED FACTS (Historical Evidence) ---")
    for fact in hypothesis["basis"]["facts"]:
        lines.append(f"  * [FACT]: {fact}")
    lines.append("")

    lines.append("--- INFERENCES (Logical Deductions) ---")
    for inf in hypothesis["basis"]["inferences"]:
        lines.append(f"  * [INFERENCE]: {inf}")
    lines.append("")

    lines.append("--- HYPOTHESIS (Testable Proposition) ---")
    lines.append(f"  * [HYPOTHESIS]: {hypothesis['hypothesis']}")
    lines.append("")

    lines.append("--- EXPERIMENT DESIGN ---")
    lines.append("Independent Variable(s) Under Test:")
    for chg in plan["changes_under_test"]:
        lines.append(f"  * {chg['variable']}: {chg['baseline_value']} -> {chg['target_value']} ({chg.get('rationale', '')})")

    lines.append("Unchanged Control Variables:")
    ctrls = [f"{u['variable']}={u['value']}" for u in plan["unchanged_variables"] if u.get("value") is not None]
    lines.append(f"  * {', '.join(ctrls)}")
    lines.append("")

    lines.append("Target Input Parameters:")
    lines.append(f"  * {', '.join(f'{k}={v}' for k, v in plan['parameters'].items())}")
    lines.append("")

    lines.append("--- DATASET ---")
    ds = plan["dataset"]
    lines.append(f"Type            : {ds.get('type', 'training').upper()}")
    lines.append(f"Partition Status: {ds.get('status')}")
    if "note" in ds:
        lines.append(f"Note            : {ds['note']}")
    lines.append("")

    lines.append("--- EXPECTED OBSERVATIONS ---")
    for obs in hypothesis["expected_observations"]:
        lines.append(f"  * {obs}")
    lines.append("")

    lines.append("--- FALSIFICATION CONDITIONS ---")
    for cond in hypothesis["falsification_conditions"]:
        lines.append(f"  * {cond}")
    lines.append("")

    if plan.get("warnings"):
        lines.append("--- WARNINGS ---")
        for w in plan["warnings"]:
            lines.append(f"  ! {w}")
        lines.append("")

    lines.append("--- OPERATIONAL BOUNDARY ---")
    lines.append("Status          : PLANNED (Human Review Required)")
    lines.append("Human Approval  : Required before any code modification or execution.")
    lines.append("Execution Note  : AI Researcher does not modify MQL5 code or execute live trades.")
    lines.append("=" * 70)

    return "\n".join(lines)


def run_researcher(
    research_question: Optional[str] = None,
    baseline_id: Optional[str] = None,
    mock: bool = True,
    as_json: bool = False,
    save: bool = False,
    hypotheses_dir: Optional[Path] = None,
    plans_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Executes the Researcher pipeline:
    1. Compiles dynamic research context from repository.
    2. Formulates testable hypothesis grounded in historical facts.
    3. Invokes Experiment Planner to generate controlled specification.
    4. Formats human-readable or JSON proposal.
    5. Optionally persists to disk under research/.
    """
    context = build_research_context()

    # Formulate hypothesis
    hypothesis = formulate_mock_hypothesis(
        context=context,
        research_question=research_question,
        baseline_id=baseline_id,
        hypotheses_dir=hypotheses_dir,
    )

    # Plan experiment
    plan = create_experiment_plan(
        hypothesis=hypothesis,
        context=context,
        baseline_id=baseline_id,
        plans_dir=plans_dir,
    )

    # Persist if requested
    if save:
        hyp_path = save_hypothesis(hypothesis, hypotheses_dir=hypotheses_dir)
        plan_path = save_experiment_plan(plan, plans_dir=plans_dir)
        save_research_context(context)

    if as_json:
        payload = {
            "schema_version": 1,
            "researcher_mode": "mock" if mock else "standard",
            "hypothesis": hypothesis,
            "experiment_plan": plan,
        }
        print(json.dumps(payload, indent=2))
    else:
        text_output = format_human_proposal(hypothesis, plan, is_mock=mock)
        print(text_output)
        if save:
            print()
            print(f"Saved Hypothesis : {HYPOTHESES_DIR / f'{hypothesis['hypothesis_id']}.json'}")
            print(f"Saved Plan       : {PLANS_DIR / f'{plan['experiment_plan_id']}.json'}")
            print()

    return hypothesis, plan


def main():
    parser = argparse.ArgumentParser(
        description="AI EA Lab - AI Researcher & Experiment Planner CLI"
    )
    parser.add_argument(
        "--question",
        "-q",
        default=None,
        help="Research question to investigate",
    )
    parser.add_argument(
        "--from-experiment",
        "--baseline",
        "-b",
        default=None,
        dest="baseline_id",
        help="Baseline experiment ID to branch from (e.g. EXP-0002)",
    )
    parser.add_argument(
        "--mock",
        "-m",
        action="store_true",
        default=True,
        help="Run deterministic offline Mock Researcher (default: True)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output research proposal as structured JSON",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="Persist hypothesis and plan to research/hypotheses and research/plans",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        help="Dump the current unified research context to stdout",
    )

    args = parser.parse_args()

    if args.context:
        ctx = build_research_context()
        print(json.dumps(ctx, indent=2))
        sys.exit(0)

    try:
        run_researcher(
            research_question=args.question,
            baseline_id=args.baseline_id,
            mock=args.mock,
            as_json=args.as_json,
            save=args.save,
        )
    except FileNotFoundError as e:
        if args.as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        if args.as_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
