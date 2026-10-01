"""
AI EA Lab - Research Decision Engine (Phase 11)

Converts experimental and audit evidence into a structured, deterministic research decision.
Enforces:
1. Deterministic rules-based evaluation (no arbitrary scores, no random ranking).
2. NO global candidate ranking, NO "winner" declaration, NO optimization scoreboards.
3. Explicit classification:
   - CONTINUE_RESEARCH
   - REVISE_PLAN
   - REJECT_EXPERIMENT
   - NEEDS_HUMAN_REVIEW
   - INFRASTRUCTURE_FAILURE
4. Clear distinction:
   - Zero trades != bad strategy performance; it indicates INSUFFICIENT trading-performance evidence.
   - Zero data (0 bars, 0 ticks) == INFRASTRUCTURE_FAILURE.
5. Dataset partitioning discipline:
   - Evaluates whether dataset splits (TRAINING, VALIDATION, UNSEEN) are configured or unconfigured placeholders.
   - Prevents unwarranted claims of out-of-sample validation.
6. Structured reasoning output with next research action guidance.
"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.research_loop_schemas import (
    DECISION_CANDIDATE_INTEGRITY_FAILURE,
    DECISION_CONTINUE_RESEARCH,
    DECISION_DATASET_INTEGRITY_FAILURE,
    DECISION_INFRASTRUCTURE_FAILURE,
    DECISION_NEEDS_HUMAN_REVIEW,
    DECISION_NEEDS_REPRODUCIBILITY_REVIEW,
    DECISION_REJECT_EXPERIMENT,
    DECISION_RESEARCH_CONFIGURATION_CHANGED,
    DECISION_REVISE_PLAN,
    FORBIDDEN_WORDS,
)
from scripts.research_periods import is_periods_configured, load_research_periods

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"


def evaluate_research_decision(
    audit: Dict[str, Any],
    metrics: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    plan: Optional[Dict[str, Any]] = None,
    periods_config: Optional[Dict[str, Any]] = None,
    research_periods_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Evaluates audit results, metrics, and plan specifications to produce a structured research decision.
    """
    reasons: List[str] = []
    risks_and_limitations: List[str] = []
    audit = audit or {}
    metrics = metrics or {}
    metadata = metadata or {}
    plan = plan or {}

    # Load periods configuration if not provided
    if periods_config is None:
        cfg_path = research_periods_path or RESEARCH_PERIODS_PATH
        periods_config = load_research_periods(cfg_path)

    # 1. Extract checks from audit
    audit_status = audit.get("status", "UNKNOWN")
    evidence_grade = audit.get("evidence_grade", "UNKNOWN")
    infra_grade = audit.get("infrastructure_evidence", "UNKNOWN")
    trading_grade = audit.get("trading_performance_evidence", "UNKNOWN")

    identity_check = audit.get("experiment_identity_check", {})
    provenance_check = audit.get("provenance_check", {})
    integrity_check = audit.get("artifact_integrity_check", {})
    tester_check = audit.get("tester_execution_check", {})
    consistency_check = audit.get("report_consistency_check", {})
    compliance_check = audit.get("plan_compliance_check", {})
    change_scope_check = audit.get("change_scope_check", {})
    dataset_check = audit.get("dataset_check", {})
    reproducibility_check = audit.get("reproducibility_check", {})

    # Extract numerical execution metrics
    bars = tester_check.get("bars", 0)
    ticks = tester_check.get("ticks", 0)
    trades = tester_check.get("trades", 0)
    zero_data = tester_check.get("zero_data", False) or (bars == 0 and ticks == 0)

    # Dataset partition status
    periods_configured = is_periods_configured(periods_config)
    dataset_type = dataset_check.get("dataset_type") or plan.get("dataset", {}).get("type", "training")
    dataset_status = "configured" if periods_configured else "unconfigured"

    # Capture audit limitations & risks
    for lim in audit.get("limitations", []):
        risks_and_limitations.append(lim)
    for risk in audit.get("overfitting_risks", []):
        risks_and_limitations.append(f"Overfitting ({risk.get('level')}): {risk.get('description')}")
    for risk in audit.get("data_leakage_risks", []):
        risks_and_limitations.append(f"Data Leakage ({risk.get('level')}): {risk.get('description')}")
    for concern in audit.get("robustness_concerns", []):
        risks_and_limitations.append(f"Robustness concern: {concern}")

    # =========================================================================
    # DECISION RULES (Deterministic priority order)
    # =========================================================================

    # RULE 1: Infrastructure Failure
    # If the tester failed, report is missing/empty, zero_data occurred, or tester check failed.
    if zero_data or tester_check.get("status") != "PASS":
        decision = DECISION_INFRASTRUCTURE_FAILURE
        summary = "Backtest execution suffered an infrastructure failure: no market bars or ticks were processed."
        reasons.append(
            f"Zero market data processed (bars={bars}, ticks={ticks}, zero_data={zero_data}). "
            "MT5 Strategy Tester was unable to execute the candidate in the specified market window."
        )
        if tester_check.get("issues"):
            reasons.extend(tester_check["issues"])
        next_action = (
            "Verify MT5 terminal configuration, Core agent logs, port 3000 availability, "
            "and market symbol/history data coverage."
        )
        rec_direction = "Resolve infrastructure execution prerequisites before re-running candidate."

    # RULE 2: Artifact Integrity / Data Corruption / Audit Failure
    elif integrity_check.get("status") != "PASS" or not integrity_check.get("hashes_verified", True):
        decision = DECISION_NEEDS_HUMAN_REVIEW
        summary = "Artifact integrity verification failed: cryptographic hashes mismatch or required files are missing."
        reasons.append("Cryptographic hash mismatch or artifact file corruption detected by Auditor.")
        if integrity_check.get("issues"):
            reasons.extend(integrity_check["issues"])
        next_action = (
            "Human review required to investigate artifact corruption, inspect candidate workspace, "
            "and verify storage integrity."
        )
        rec_direction = "Halt automated iteration until artifact hash discrepancies are resolved."

    elif audit_status == "INVALID":
        decision = DECISION_NEEDS_HUMAN_REVIEW
        summary = "Auditor classified experiment as INVALID due to methodological or structural defects."
        reasons.append(f"Audit status is INVALID. Details: {identity_check.get('details', '')}")
        next_action = "Conduct human review of the experiment archive and audit log."
        rec_direction = "Investigate audit failure causes before formulating new hypotheses."

    # RULE 2B: Phase 15 Reproducibility / Integrity Failures (Evidence Issues, NOT Strategy Rejection)
    elif reproducibility_check.get("dimensions", {}).get("dataset_reproducibility") == "FAIL":
        decision = DECISION_RESEARCH_CONFIGURATION_CHANGED
        summary = "Reproducibility audit failed due to changes in research periods or dataset partition integrity."
        reasons.append("Research period boundaries or dataset configuration changed relative to recorded experiment state.")
        if reproducibility_check.get("issues"):
            reasons.extend(reproducibility_check["issues"])
        next_action = "Re-verify config/research_periods.json integrity before proceeding."
        rec_direction = "Preserve historical research partition boundaries without unverified mutations."

    elif reproducibility_check.get("dimensions", {}).get("candidate_reproducibility") == "FAIL":
        decision = DECISION_CANDIDATE_INTEGRITY_FAILURE
        summary = "Candidate artifact integrity verification failed (source or binary hash mismatch)."
        reasons.append("Candidate source or EX5 binary hash on disk does not match recorded experiment metadata.")
        if reproducibility_check.get("issues"):
            reasons.extend(reproducibility_check["issues"])
        next_action = "Inspect candidate directory and restore pristine candidate artifact from archive."
        rec_direction = "Prevent unauthorized or accidental candidate file modifications."

    elif reproducibility_check.get("status") in {"INSUFFICIENT", "FAIL"} or any(
        v == "FAIL" for v in reproducibility_check.get("dimensions", {}).values()
    ):
        decision = DECISION_NEEDS_REPRODUCIBILITY_REVIEW
        summary = "Reproducibility audit identified infrastructure or artifact evidence gaps."
        reasons.append(f"Reproducibility check issue: {reproducibility_check.get('details', '')}")
        if reproducibility_check.get("issues"):
            reasons.extend(reproducibility_check["issues"])
        next_action = "Conduct reproducibility review and verify experiment artifact completeness."
        rec_direction = "Resolve evidence infrastructure gaps before making research claims."

    # RULE 3: Scope Violation / Plan Non-Compliance
    elif change_scope_check.get("status") != "PASS":
        decision = DECISION_REJECT_EXPERIMENT
        summary = "Candidate source code contains unauthorized modifications outside approved plan scope."
        unauthorized = change_scope_check.get("unauthorized_changes", [])
        reasons.append(f"Unauthorized code changes detected: {unauthorized}")
        next_action = "Reject candidate artifact and review Developer adapter constraints."
        rec_direction = "Ensure future candidate generation restricts diffs strictly to authorized parameters."

    elif compliance_check.get("status") == "NON_COMPLIANT":
        decision = DECISION_REJECT_EXPERIMENT
        summary = "Executed backtest parameters strictly deviated from approved experiment plan."
        reasons.append(f"Plan compliance failure: {compliance_check.get('details', '')}")
        if compliance_check.get("deviations"):
            reasons.extend(compliance_check["deviations"])
        next_action = "Reject experiment and re-align backtest configuration with approved plan."
        rec_direction = "Ensure tester runner parameter staging respects plan parameters."

    # RULE 4: Zero Trades / Insufficient Trading-Performance Evidence
    elif trades == 0 or trading_grade == "INSUFFICIENT":
        # Check whether the plan was an infrastructure verification plan
        # or expected trading observations
        plan_expected = " ".join(str(o).lower() for o in plan.get("expected_observations", []))
        is_infra_verification = (
            "candidate code is generated" in plan_expected
            or "binary created" in plan_expected
            or "pipeline" in plan_expected
            or "smoke test" in plan_expected
        )

        reasons.append(
            f"Candidate executed with 0 trades across {bars:,} bars and {ticks:,} ticks. "
            "Trading-performance evidence is INSUFFICIENT."
        )
        reasons.append(
            "IMPORTANT: Zero trades must NOT be interpreted as 'bad strategy performance'; "
            "it indicates signal entry conditions were unfulfilled in this test window."
        )

        if not periods_configured:
            reasons.append(
                "Research periods in config/research_periods.json are unconfigured placeholders. "
                "Dataset partition cannot claim formal out-of-sample validation."
            )

        if is_infra_verification and infra_grade == "STRONG":
            decision = DECISION_CONTINUE_RESEARCH
            summary = (
                "Infrastructure validation succeeded. Candidate was verified, staged, and executed "
                "in MT5 Strategy Tester. Trading-performance evidence remains insufficient."
            )
            next_action = (
                "Infrastructure validated. Formulate next research hypothesis focusing on signal "
                "generation conditions, indicator sensitivity, or OnTick() trading logic."
            )
            rec_direction = (
                "Transition from infrastructure smoke testing to controlled parameter testing, "
                "or examine signal threshold responsiveness."
            )
        else:
            decision = DECISION_REVISE_PLAN
            summary = (
                "Experiment executed cleanly, but produced 0 trades. "
                "Trading-performance evidence is insufficient to evaluate strategy behavior."
            )
            next_action = (
                "Revise experiment plan: investigate why entry signals did not trigger on "
                f"{plan.get('baseline', {}).get('symbol', 'GBPUSD')} "
                f"{plan.get('baseline', {}).get('timeframe', 'M15')}. Consider testing smaller "
                "fast MA periods, longer market windows, or verifying OnTick() trade conditions."
            )
            rec_direction = (
                "Formulate hypothesis adjusting crossover sensitivity or exploring different "
                "timeframes/volatility regimes."
            )

    # RULE 5: Unconfigured Dataset Warning on Otherwise Passing Strategy
    elif not periods_configured:
        decision = DECISION_REVISE_PLAN
        summary = (
            "Backtest produced trades and infrastructure passed, but research periods are unconfigured placeholders. "
            "Formal validation cannot be claimed."
        )
        reasons.append(
            "Dataset partitions in config/research_periods.json are unconfigured. "
            "Evaluating candidate on unpartitioned data creates risk of informal overfitting."
        )
        next_action = (
            "Configure concrete date boundaries in config/research_periods.json for TRAINING, "
            "VALIDATION, and UNSEEN before claiming out-of-sample validation."
        )
        rec_direction = "Freeze research period boundaries before proceeding to validation phase."

    # RULE 6: Clean Success (Infrastructure and Trading Evidence Present)
    else:
        decision = DECISION_CONTINUE_RESEARCH
        summary = (
            "Experiment completed with valid infrastructure evidence and observable trading activity "
            "under configured dataset partitions."
        )
        reasons.append(
            f"Execution validated: {bars:,} bars, {ticks:,} ticks, {trades} trades. "
            f"Infrastructure grade: {infra_grade}, Trading performance grade: {trading_grade}."
        )
        reasons.append("Plan parameters and candidate change scope were strictly verified.")
        next_action = (
            "Analyze trading-performance metrics, examine drawdown and stability, "
            "and formulate the next hypothesis testing one independent variable."
        )
        rec_direction = "Proceed to next sequential parameter hypothesis or adjacent validation period."

    # =========================================================================
    # BUILD FINAL DECISION ARTIFACT
    # =========================================================================
    decision_artifact: Dict[str, Any] = {
        "schema_version": 1,
        "decision": decision,
        "summary": summary,
        "reasons": reasons,
        "evidence_assessment": {
            "audit_id": audit.get("audit_id"),
            "experiment_id": audit.get("experiment_id"),
            "candidate_id": audit.get("candidate_id"),
            "plan_id": audit.get("plan_id"),
            "hypothesis_id": audit.get("hypothesis_id"),
            "audit_status": audit_status,
            "evidence_grade": evidence_grade,
            "infrastructure_evidence": infra_grade,
            "trading_performance_evidence": trading_grade,
            "evaluation_stage": metadata.get("evaluation_type", "training") if isinstance(metadata, dict) else "training",
            "training_experiment_id": metadata.get("training_experiment_id") if isinstance(metadata, dict) else None,
            "bars": bars,
            "ticks": ticks,
            "trades": trades,
            "zero_data": zero_data,
            "plan_compliance": compliance_check.get("status", "UNKNOWN"),
            "change_scope": change_scope_check.get("status", "UNKNOWN"),
            "reproducibility": reproducibility_check.get("status", "UNKNOWN"),
        },
        "dataset_discipline": {
            "status": dataset_status,
            "dataset_type": dataset_type,
            "periods_configured": periods_configured,
            "note": (
                "Research periods in config/research_periods.json are unconfigured placeholders."
                if not periods_configured
                else "Research periods are frozen and configured."
            ),
        },
        "risks_and_limitations": risks_and_limitations,
        "next_action": next_action,
        "recommended_hypothesis_direction": rec_direction,
        "evaluated_at": datetime.now().astimezone().isoformat(),
    }

    # Prohibited words check
    serialized = json.dumps(decision_artifact).lower()
    for forbidden in FORBIDDEN_WORDS:
        if forbidden in serialized:
            raise ValueError(f"Prohibited ranking/optimization term found in decision output: '{forbidden}'.")

    return decision_artifact


def format_human_readable_decision(decision: Dict[str, Any]) -> str:
    """
    Formats the decision artifact for clean console reporting.
    """
    d_val = decision.get("decision", "UNKNOWN")
    ev = decision.get("evidence_assessment", {})
    ds = decision.get("dataset_discipline", {})

    lines = [
        "=" * 65,
        "AI-EA-LAB -- RESEARCH DECISION ENGINE (PHASE 11)",
        "=" * 65,
        f"Research Decision:         {d_val}",
        f"Experiment Under Review:   {ev.get('experiment_id', 'UNKNOWN')}",
        f"Audit ID:                  {ev.get('audit_id', 'UNKNOWN')}",
        f"Candidate:                 {ev.get('candidate_id') or 'None'}",
        f"Plan:                      {ev.get('plan_id') or 'None'}",
        f"Hypothesis:                {ev.get('hypothesis_id') or 'None'}",
        "",
        "--- EVIDENCE GRADES ---",
        f"  Audit Status:            {ev.get('audit_status')}",
        f"  Overall Evidence Grade:  {ev.get('evidence_grade')}",
        f"  Infrastructure Evidence: {ev.get('infrastructure_evidence')}",
        f"  Trading Performance:     {ev.get('trading_performance_evidence')}",
        f"  Execution Counts:        {ev.get('bars', 0):,} bars, {ev.get('ticks', 0):,} ticks, {ev.get('trades', 0)} trades",
        f"  Zero Data Flag:          {ev.get('zero_data')}",
        "",
        "--- DATASET DISCIPLINE ---",
        f"  Partition Status:        {ds.get('status')} ({ds.get('dataset_type')})",
        f"  Note:                    {ds.get('note')}",
        "",
        "--- DECISION SUMMARY & REASONS ---",
        f"Summary: {decision.get('summary')}",
    ]

    for r in decision.get("reasons", []):
        lines.append(f"  * {r}")

    lines.append("")
    lines.append("--- NEXT RESEARCH ACTION ---")
    lines.append(f"  Action:    {decision.get('next_action')}")
    lines.append(f"  Direction: {decision.get('recommended_hypothesis_direction')}")

    if decision.get("risks_and_limitations"):
        lines.append("")
        lines.append("--- RISKS & LIMITATIONS ---")
        for lim in decision["risks_and_limitations"]:
            lines.append(f"  ! {lim}")

    lines.append("=" * 65)
    return "\n".join(lines)
