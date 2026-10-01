"""
Auditor LLM / Evaluation Adapter Interface (Phase 10)

Provides an extensible interface for evidence auditing adapters
(Local models, Gemini, Claude, OpenAI, or Mock).
Zero external SDK dependencies. No network calls or credentials required.
Includes MockAuditorAdapter for deterministic local execution and testing.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseAuditorAdapter(ABC):
    """
    Abstract interface for AI Auditor evaluation adapters.
    """

    @abstractmethod
    def evaluate_evidence(self, audit_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates structural audit checks and synthesizes factual observations,
        interpretations, risks, limitations, and follow-up research questions.
        """
        pass


class MockAuditorAdapter(BaseAuditorAdapter):
    """
    Deterministic mock adapter for offline testing without credentials or network calls.
    Consumes verified structural audit checks to produce grounded, objective audit evaluations.
    Strictly separates FACTS from INTERPRETATIONS and RISKS.
    """

    def evaluate_evidence(self, audit_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synthesizes deterministic evidence evaluation from structural audit context.
        """
        exp_id = audit_context.get("experiment_id", "UNKNOWN")
        cand_id = audit_context.get("candidate_id")
        tester_check = audit_context.get("tester_execution_check", {})
        integrity_check = audit_context.get("artifact_integrity_check", {})
        provenance_check = audit_context.get("provenance_check", {})
        compliance_check = audit_context.get("plan_compliance_check", {})
        change_scope_check = audit_context.get("change_scope_check", {})
        dataset_check = audit_context.get("dataset_check", {})
        report_consistency = audit_context.get("report_consistency_check", {})

        bars = tester_check.get("bars", 0)
        ticks = tester_check.get("ticks", 0)
        trades = tester_check.get("trades", 0)
        zero_data = tester_check.get("zero_data", False)

        # 1. Collect Facts / Observations
        observations = []
        observations.append(f"Experiment '{exp_id}' recorded {bars:,} bars and {ticks:,} ticks.")
        if cand_id:
            observations.append(f"Strategy Tester report identified candidate binary '{cand_id}'.")
        observations.append(f"Strategy Tester recorded exactly {trades} trades.")

        if integrity_check.get("status") == "PASS":
            observations.append("All available SHA-256 cryptographic hashes matched recorded metadata.")
        elif integrity_check.get("status") == "FAIL":
            for issue in integrity_check.get("issues", []):
                observations.append(f"Integrity check issue: {issue}")

        if provenance_check.get("status") == "PASS":
            lineage = provenance_check.get("lineage", {})
            observations.append(
                f"Lineage confirmed: {lineage.get('hypothesis')} -> {lineage.get('plan')} -> "
                f"{lineage.get('candidate')} -> {lineage.get('experiment')}."
            )
        elif provenance_check.get("status") == "NOT_APPLICABLE":
            observations.append("Provenance check not applicable: experiment is a canonical baseline.")

        # 2. Interpretations (strictly separated from facts)
        interpretations = []
        if zero_data:
            interpretations.append(
                "The Strategy Tester processed zero bars and zero ticks. The test failed to execute market simulation."
            )
        elif trades == 0:
            interpretations.append(
                "The experiment successfully executed in the MT5 Strategy Tester, demonstrating candidate execution "
                "and environment data processing."
            )
            interpretations.append(
                "Because zero trades occurred, this experiment provides no empirical evidence regarding trading strategy "
                "profitability, win rate, or market drawdown."
            )
        else:
            interpretations.append(
                f"The candidate generated {trades} trade signals, providing sample execution data for analysis."
            )

        if compliance_check.get("status") == "COMPLIANT":
            interpretations.append("The executed backtest parameters strictly matched the approved experiment plan.")
        elif compliance_check.get("status") == "NON_COMPLIANT":
            interpretations.append(
                f"The executed backtest deviated from the approved plan: {'; '.join(compliance_check.get('deviations', []))}."
            )

        if change_scope_check.get("status") == "PASS":
            interpretations.append("Code changes under test were strictly confined to authorized parameters.")
        elif change_scope_check.get("status") == "FAIL":
            interpretations.append(
                f"Unauthorized code changes were detected: {'; '.join(change_scope_check.get('unauthorized_changes', []))}."
            )

        # 3. Overfitting Risks
        overfitting_risks = []
        if dataset_check.get("status") == "UNCONFIGURED":
            overfitting_risks.append({
                "risk_type": "unconfigured_dataset_partitioning",
                "level": "POSSIBLE",
                "description": (
                    "Research periods are unconfigured placeholders. Repeated testing without frozen "
                    "in-sample/out-of-sample partitions risks informal overfitting."
                ),
            })
        else:
            overfitting_risks.append({
                "risk_type": "repeated_window_evaluation",
                "level": "OBSERVED" if audit_context.get("experiments_on_same_window", 1) > 2 else "POSSIBLE",
                "description": "Parameters evaluated against a single historical window risk curve-fitting to specific volatility regimes.",
            })

        # 4. Data Leakage Risks
        data_leakage_risks = []
        if dataset_check.get("status") == "UNCONFIGURED":
            data_leakage_risks.append({
                "risk_type": "partition_boundary_verification",
                "level": "UNKNOWN",
                "description": "Unable to determine from available evidence because dataset partition dates are unconfigured.",
            })
        else:
            data_leakage_risks.append({
                "risk_type": "temporal_leakage",
                "level": "OBSERVED" if audit_context.get("has_leakage", False) else "POSSIBLE",
                "description": "No evidence of look-ahead bias or future-leakage identified in tester inputs.",
            })

        # 5. Robustness Concerns
        robustness_concerns = []
        if trades == 0:
            robustness_concerns.append(
                "No trading-performance evidence exists because the candidate produced zero trades."
            )
        robustness_concerns.append(
            "Evidence is derived from a single market window and single instrument (GBPUSD M15); multi-regime robustness is unproven."
        )

        # 6. Evidence Gaps
        evidence_gaps = []
        if dataset_check.get("status") == "UNCONFIGURED":
            evidence_gaps.append("Validation and unseen out-of-sample research periods are not configured.")
        if trades == 0:
            evidence_gaps.append(
                "Trade execution, slippage impact, and position holding times could not be observed."
            )

        # 7. Limitations
        limitations = []
        if trades == 0:
            limitations.append(
                "This experiment validates infrastructure execution and candidate compilation rather than trading strategy performance."
            )
        limitations.append(
            "Offline Strategy Tester backtest results do not account for live broker spread fluctuations, slippage, or latency."
        )

        # 8. Follow-up Questions for Researcher
        follow_up_questions = []
        if trades == 0:
            follow_up_questions.append(
                "What market conditions or indicator threshold adjustments would enable signal generation in OnTick()?"
            )
        follow_up_questions.append(
            "How does candidate parameter sensitivity vary across differing volatility regimes or adjacent months?"
        )

        # 9. Determine Status and Evidence Grades
        if zero_data or tester_check.get("status") == "INVALID" or report_consistency.get("status") == "FAIL":
            status = "INVALID"
            infra_grade = "INSUFFICIENT"
            trading_grade = "INSUFFICIENT"
            evidence_grade = "INSUFFICIENT"
        elif (
            integrity_check.get("status") == "FAIL"
            or compliance_check.get("status") == "NON_COMPLIANT"
            or change_scope_check.get("status") == "FAIL"
        ):
            status = "NEEDS_REVIEW"
            infra_grade = "LIMITED"
            trading_grade = "INSUFFICIENT"
            evidence_grade = "LIMITED"
        else:
            status = "PASS"
            infra_grade = "STRONG"
            trading_grade = "INSUFFICIENT" if trades == 0 else "ADEQUATE"
            evidence_grade = "LIMITED" if trades == 0 else "ADEQUATE"

        return {
            "status": status,
            "evidence_grade": evidence_grade,
            "infrastructure_evidence": infra_grade,
            "trading_performance_evidence": trading_grade,
            "observations": observations,
            "interpretations": interpretations,
            "overfitting_risks": overfitting_risks,
            "data_leakage_risks": data_leakage_risks,
            "robustness_concerns": robustness_concerns,
            "evidence_gaps": evidence_gaps,
            "limitations": limitations,
            "follow_up_questions": follow_up_questions,
        }
