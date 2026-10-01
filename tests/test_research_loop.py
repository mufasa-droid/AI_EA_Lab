"""
Automated Test Suite for AI EA Lab - Phase 11: Controlled Autonomous Research Loop

Tests:
1. Iteration creation and initial safe halt at AWAITING_APPROVAL.
2. Unique, sequential, monotonic iteration IDs (ITER-XXXX).
3. Provenance preservation across HYP -> PLAN -> CAND -> EXP -> AUD -> DECISION.
4. Approval required: unapproved iterations refuse candidate development.
5. Approval rejection: transitions to BLOCKED and records reason.
6. Invalid state transitions rejected by state machine.
7. Successful state transitions recorded in history.
8. Candidate verification failure halts loop in FAILED.
9. Candidate compile failure halts loop in FAILED.
10. MT5 Strategy Tester failure halts loop in FAILED.
11. Missing report artifact handled cleanly as failure.
12. Zero-data detection classifies as INFRASTRUCTURE_FAILURE.
13. Zero-trade handling classifies as REVISE_PLAN with INSUFFICIENT trading evidence.
14. Audit failure classifies as NEEDS_HUMAN_REVIEW / REJECT_EXPERIMENT.
15. Unconfigured dataset surfaced explicitly in decision and metadata.
16. Hash mismatch detected and routed to NEEDS_HUMAN_REVIEW.
17. Decision generation complies with safety invariants (no rankings, no scores, no winners).
18. Iteration artifact persistence in research/iterations/ITER-XXXX/.
19. Baseline EA immutability: ea/TestEA.mq5 remains strictly untouched.
20. Complete successful orchestration using deterministic mocks.
"""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auditor.llm.base import BaseAuditorAdapter
from developer.llm.base import BaseDeveloperAdapter
from scripts.auditor import run_audit
from scripts.auditor_schemas import (
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_NON_COMPLIANT,
    GRADE_ADEQUATE,
    GRADE_INSUFFICIENT,
    GRADE_LIMITED,
    GRADE_STRONG,
    STATUS_INVALID,
    STATUS_PASS,
)
from scripts.developer import run_developer
from scripts.research_decision import (
    evaluate_research_decision,
    format_human_readable_decision,
)
from scripts.research_loop import ResearchLoop, format_human_readable_iteration
from scripts.research_loop_schemas import (
    ALLOWED_STATES,
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    DECISION_CONTINUE_RESEARCH,
    DECISION_INFRASTRUCTURE_FAILURE,
    DECISION_NEEDS_HUMAN_REVIEW,
    DECISION_REJECT_EXPERIMENT,
    DECISION_REVISE_PLAN,
    FORBIDDEN_WORDS,
    STATE_APPROVED,
    STATE_AUDITED,
    STATE_AUDITING,
    STATE_AWAITING_APPROVAL,
    STATE_BACKTESTING,
    STATE_BLOCKED,
    STATE_CANDIDATE_READY,
    STATE_COMPLETED,
    STATE_CREATED,
    STATE_DECIDED,
    STATE_DEVELOPING,
    STATE_EXPERIMENT_CREATED,
    STATE_FAILED,
    STATE_PLANNED,
    STATE_RESEARCHING,
    get_next_iteration_id,
    validate_iteration_dict,
    validate_state_transition,
)


class TestResearchLoop(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.iterations_dir = self.temp_dir / "research" / "iterations"
        self.hypotheses_dir = self.temp_dir / "research" / "hypotheses"
        self.plans_dir = self.temp_dir / "research" / "plans"
        self.candidates_dir = self.temp_dir / "developer" / "candidates"
        self.experiments_dir = self.temp_dir / "experiments"
        self.audits_dir = self.temp_dir / "audits"
        self.ea_dir = self.temp_dir / "ea"
        self.config_dir = self.temp_dir / "config"
        self.mt5_data_dir = self.temp_dir / "mt5_data"

        for d in [
            self.iterations_dir,
            self.hypotheses_dir,
            self.plans_dir,
            self.candidates_dir,
            self.experiments_dir,
            self.audits_dir,
            self.ea_dir,
            self.config_dir,
            self.mt5_data_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        # 1. Setup baseline EA in ea_dir
        self.baseline_ea_source = (
            "// Baseline TestEA\n"
            "input int FastMAPeriod = 10;\n"
            "input int SlowMAPeriod = 20;\n"
            "input double LotSize = 0.01;\n"
            "void OnTick() {}\n"
        )
        self.ea_file = self.ea_dir / "TestEA.mq5"
        self.ea_file.write_text(self.baseline_ea_source, encoding="utf-8")
        self.ea_hash_before = hashlib.sha256(self.ea_file.read_bytes()).hexdigest()

        # 2. Setup baseline experiment EXP-0002
        self.base_exp_dir = self.experiments_dir / "EXP-0002"
        self.base_exp_dir.mkdir(parents=True, exist_ok=True)
        self.base_meta = {
            "experiment_id": "EXP-0002",
            "created_at": "2026-09-28T18:58:07+01:00",
            "ea": "TestEA",
            "symbol": "GBPUSD",
            "timeframe": "M15",
            "from": "2024.01.01",
            "to": "2024.02.01",
            "inputs": {
                "FastMAPeriod": "10",
                "SlowMAPeriod": "20",
                "LotSize": "0.01",
            },
            "status": "COMPLETED",
        }
        (self.base_exp_dir / "metadata.json").write_text(
            json.dumps(self.base_meta, indent=2), encoding="utf-8"
        )
        self.base_metrics = {
            "metrics": {
                "bars": 2120,
                "ticks": 125602,
                "total_trades": 0,
                "total_net_profit": 0.0,
                "profit_factor": 0.0,
            },
            "validation": {
                "test_executed": True,
                "report_non_empty": True,
            },
        }
        (self.base_exp_dir / "metrics.json").write_text(
            json.dumps(self.base_metrics, indent=2), encoding="utf-8"
        )
        (self.base_exp_dir / "report.htm").write_text("<html>Baseline Report</html>", encoding="utf-8")

        # Manifest
        manifest_data = {
            "schema_version": 1,
            "total_experiments": 1,
            "experiments": [
                {
                    "id": "EXP-0002",
                    "ea": "TestEA",
                    "symbol": "GBPUSD",
                    "timeframe": "M15",
                    "from": "2024.01.01",
                    "to": "2024.02.01",
                    "total_trades": 0,
                    "validation_passed": True,
                }
            ],
        }
        (self.experiments_dir / "manifest.json").write_text(
            json.dumps(manifest_data, indent=2), encoding="utf-8"
        )

        # 3. Setup config.json
        self.config_path = self.temp_dir / "config.json"
        self.config_data = {
            "mt5_terminal": str(self.temp_dir / "terminal64.exe"),
            "mt5_data": str(self.mt5_data_dir),
            "ea": {"name": "TestEA"},
            "backtest": {
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "model": 1,
                "from": "2024.01.01",
                "to": "2024.02.01",
                "deposit": 10000,
                "currency": "USD",
                "leverage": "1:100",
            },
        }
        self.config_path.write_text(json.dumps(self.config_data, indent=2), encoding="utf-8")

        # 4. Setup research_periods.json (unconfigured by default)
        self.research_periods_path = self.config_dir / "research_periods.json"
        self.periods_data = {
            "schema_version": 1,
            "status": "unconfigured",
            "periods": {
                "training": {"from": None, "to": None},
                "validation": {"from": None, "to": None},
                "unseen": {"from": None, "to": None},
            },
        }
        self.research_periods_path.write_text(
            json.dumps(self.periods_data, indent=2), encoding="utf-8"
        )

        # Initialize ResearchLoop
        self.loop = ResearchLoop(
            iterations_dir=self.iterations_dir,
            hypotheses_dir=self.hypotheses_dir,
            plans_dir=self.plans_dir,
            candidates_dir=self.candidates_dir,
            experiments_dir=self.experiments_dir,
            audits_dir=self.audits_dir,
            ea_dir=self.ea_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
        )

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    # TEST 1: Iteration creation
    def test_01_iteration_creation(self):
        """Test creating an iteration halts safely at AWAITING_APPROVAL with PENDING status."""
        it = self.loop.create_iteration(question="Test crossover sensitivity?", baseline_id="EXP-0002")
        self.assertEqual(it["iteration_id"], "ITER-0001")
        self.assertEqual(it["status"], STATE_AWAITING_APPROVAL)
        self.assertEqual(it["approval_status"], APPROVAL_PENDING)
        self.assertIsNotNone(it["hypothesis_id"])
        self.assertIsNotNone(it["plan_id"])
        self.assertIsNone(it["completed_at"])
        # Verify state history recorded transition
        states = [h["to_state"] for h in it["state_history"]]
        self.assertIn(STATE_CREATED, states)
        self.assertIn(STATE_AWAITING_APPROVAL, states)

    # TEST 2: Unique iteration IDs
    def test_02_unique_iteration_ids(self):
        """Test sequential monotonic iteration IDs without overwriting."""
        id1 = get_next_iteration_id(self.iterations_dir)
        (self.iterations_dir / id1).mkdir()
        id2 = get_next_iteration_id(self.iterations_dir)
        (self.iterations_dir / id2).mkdir()
        id3 = get_next_iteration_id(self.iterations_dir)

        self.assertEqual(id1, "ITER-0001")
        self.assertEqual(id2, "ITER-0002")
        self.assertEqual(id3, "ITER-0003")

    # TEST 3: Provenance preservation
    def test_03_provenance_preservation(self):
        """Test that provenance block is populated and preserved."""
        it = self.loop.create_iteration(question="Provenance test?", baseline_id="EXP-0002")
        self.assertEqual(it["provenance"]["hypothesis"], it["hypothesis_id"])
        self.assertEqual(it["provenance"]["plan"], it["plan_id"])
        self.assertIn("candidate", it["provenance"])
        self.assertIn("experiment", it["provenance"])
        self.assertIn("audit", it["provenance"])

    # TEST 4: Approval required
    def test_04_approval_required(self):
        """Test that unapproved iteration halts and refuses candidate development."""
        it = self.loop.create_iteration(question="Approval required test?", baseline_id="EXP-0002")
        iter_id = it["iteration_id"]
        res = self.loop.run_iteration(iter_id)
        self.assertIn("is not approved", res["error"])
        # State must remain in AWAITING_APPROVAL
        reloaded = self.loop.load_iteration(iter_id)
        self.assertEqual(reloaded["status"], STATE_AWAITING_APPROVAL)
        self.assertEqual(reloaded["approval_status"], APPROVAL_PENDING)

    # TEST 5: Approval rejection
    def test_05_approval_rejection(self):
        """Test rejecting an iteration transitions to BLOCKED and sets REJECTED."""
        it = self.loop.create_iteration(question="Reject test?", baseline_id="EXP-0002")
        iter_id = it["iteration_id"]
        res = self.loop.reject_iteration(iter_id, reviewer="Senior Trader", note="Parameter unsafe")
        self.assertEqual(res["status"], STATE_BLOCKED)
        self.assertEqual(res["approval_status"], APPROVAL_REJECTED)
        self.assertEqual(res["approval"]["reviewed_by"], "Senior Trader")

    # TEST 6: Invalid state transitions
    def test_06_invalid_state_transition(self):
        """Test invalid transitions like CREATED -> AUDITING or APPROVED -> BACKTESTING fail."""
        valid, msg = validate_state_transition(STATE_CREATED, STATE_AUDITING)
        self.assertFalse(valid)
        self.assertIn("Invalid state transition", msg)

        valid, msg = validate_state_transition(STATE_APPROVED, STATE_BACKTESTING)
        self.assertFalse(valid)

        valid, msg = validate_state_transition(STATE_COMPLETED, STATE_DEVELOPING)
        self.assertFalse(valid)

    # TEST 7: Successful state transitions
    def test_07_successful_state_transition(self):
        """Test valid state transitions pass validation."""
        valid, _ = validate_state_transition(STATE_CREATED, STATE_RESEARCHING)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_RESEARCHING, STATE_PLANNED)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_PLANNED, STATE_AWAITING_APPROVAL)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_AWAITING_APPROVAL, STATE_APPROVED)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_APPROVED, STATE_DEVELOPING)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_DEVELOPING, STATE_CANDIDATE_READY)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_CANDIDATE_READY, STATE_BACKTESTING)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_BACKTESTING, STATE_EXPERIMENT_CREATED)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_EXPERIMENT_CREATED, STATE_AUDITING)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_AUDITING, STATE_AUDITED)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_AUDITED, STATE_DECIDED)
        self.assertTrue(valid)
        valid, _ = validate_state_transition(STATE_DECIDED, STATE_COMPLETED)
        self.assertTrue(valid)

    # TEST 8: Candidate verification failure
    def test_08_candidate_verification_failure(self):
        """Test candidate verification failure transitions state to FAILED."""
        # Create iteration and approve
        it = self.loop.create_iteration(question="Verif fail test?", baseline_id="EXP-0002")
        iter_id = it["iteration_id"]
        self.loop.approve_iteration(iter_id)

        # Manually alter state to CANDIDATE_READY with fake non-existent candidate
        it = self.loop.load_iteration(iter_id)
        it["status"] = STATE_CANDIDATE_READY
        it["candidate_id"] = "CAND-9999"
        (self.iterations_dir / iter_id / "iteration.json").write_text(json.dumps(it, indent=2))

        res = self.loop.run_iteration(iter_id)
        self.assertEqual(res["status"], STATE_FAILED)
        self.assertIn("Candidate verification failed", res["error"])

    # TEST 9: Compile failure
    def test_09_compile_failure(self):
        """Test developer compile failure halts loop in FAILED."""
        class FailingDevAdapter(BaseDeveloperAdapter):
            def develop_candidate(self, plan, source):
                # Return modified source with intentional syntax error
                return {"modified_source": "syntax error bad code;\n"}

        plan_data = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0009",
            "hypothesis_id": "HYP-0009",
            "created_at": "2026-09-30T00:00:00+01:00",
            "title": "Compile Fail Test Plan",
            "research_question": "Does compile failure halt state machine in FAILED?",
            "objective": "Test compile failure handling.",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            },
            "dataset": {"type": "training", "from": "2024.01.01", "to": "2024.02.01"},
            "changes_under_test": [
                {
                    "variable": "FastMAPeriod",
                    "baseline_value": "10",
                    "target_value": "5",
                    "change_type": "parameter_adjustment",
                }
            ],
            "unchanged_variables": [{"variable": "SlowMAPeriod", "value": "20"}],
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "observations": ["history_quality_percent"],
            "expected_observations": ["history_quality_percent"],
            "falsification_conditions": ["Compile error"],
            "human_review_required": True,
            "status": "planned",
        }
        (self.plans_dir / "PLAN-0009.json").write_text(json.dumps(plan_data, indent=2))

        loop = ResearchLoop(
            iterations_dir=self.iterations_dir,
            hypotheses_dir=self.hypotheses_dir,
            plans_dir=self.plans_dir,
            candidates_dir=self.candidates_dir,
            experiments_dir=self.experiments_dir,
            audits_dir=self.audits_dir,
            ea_dir=self.ea_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            developer_adapter=FailingDevAdapter(),
        )

        it = loop.create_iteration(plan_id="PLAN-0009")
        iter_id = it["iteration_id"]
        loop.approve_iteration(iter_id)

        res = loop.run_iteration(iter_id)
        self.assertEqual(res["status"], STATE_FAILED)

    # TEST 10: MT5 Strategy Tester failure
    def test_10_mt5_failure(self):
        """Test MT5 execution failure transitions state to FAILED."""
        def failing_launcher(cmd, timeout):
            return {"exit_code": 1, "timeout": False}

        # Setup valid plan with non-trade observations so feasibility passes
        plan_data = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0010",
            "hypothesis_id": "HYP-0010",
            "created_at": "2026-09-30T00:00:00+01:00",
            "title": "MT5 Failure Test Plan",
            "research_question": "Does failure halt gracefully?",
            "objective": "Verify MT5 failure handling.",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            },
            "dataset": {"type": "training", "from": "2024.01.01", "to": "2024.02.01"},
            "changes_under_test": [
                {
                    "variable": "FastMAPeriod",
                    "baseline_value": "10",
                    "target_value": "5",
                    "change_type": "parameter_adjustment",
                }
            ],
            "unchanged_variables": [{"variable": "SlowMAPeriod", "value": "20"}],
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "observations": ["Candidate code compiled."],
            "expected_observations": ["Candidate code compiled."],
            "falsification_conditions": ["Compilation fails."],
            "human_review_required": True,
            "status": "planned",
        }
        (self.plans_dir / "PLAN-0010.json").write_text(json.dumps(plan_data, indent=2))

        loop = ResearchLoop(
            iterations_dir=self.iterations_dir,
            hypotheses_dir=self.hypotheses_dir,
            plans_dir=self.plans_dir,
            candidates_dir=self.candidates_dir,
            experiments_dir=self.experiments_dir,
            audits_dir=self.audits_dir,
            ea_dir=self.ea_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=failing_launcher,
        )

        it = loop.create_iteration(plan_id="PLAN-0010")
        iter_id = it["iteration_id"]
        loop.approve_iteration(iter_id)
        res = loop.run_iteration(iter_id, allow_unconfigured_dates=True)
        self.assertEqual(res["status"], STATE_FAILED)

    # TEST 11: Missing report artifact
    def test_11_missing_report(self):
        """Test missing report artifact results in failure."""
        def missing_report_launcher(cmd, timeout):
            return {"exit_code": 0, "timeout": False}

        plan_data = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0011",
            "hypothesis_id": "HYP-0011",
            "created_at": "2026-09-30T00:00:00+01:00",
            "title": "Missing Report Plan",
            "research_question": "Report missing?",
            "objective": "Verify missing report handling.",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            },
            "dataset": {"type": "training", "from": "2024.01.01", "to": "2024.02.01"},
            "changes_under_test": [
                {
                    "variable": "FastMAPeriod",
                    "baseline_value": "10",
                    "target_value": "5",
                    "change_type": "parameter_adjustment",
                }
            ],
            "unchanged_variables": [{"variable": "SlowMAPeriod", "value": "20"}],
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "observations": ["Candidate code compiled."],
            "expected_observations": ["Candidate code compiled."],
            "falsification_conditions": ["Compilation fails."],
            "human_review_required": True,
            "status": "planned",
        }
        (self.plans_dir / "PLAN-0011.json").write_text(json.dumps(plan_data, indent=2))

        loop = ResearchLoop(
            iterations_dir=self.iterations_dir,
            hypotheses_dir=self.hypotheses_dir,
            plans_dir=self.plans_dir,
            candidates_dir=self.candidates_dir,
            experiments_dir=self.experiments_dir,
            audits_dir=self.audits_dir,
            ea_dir=self.ea_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=missing_report_launcher,
        )

        it = loop.create_iteration(plan_id="PLAN-0011")
        iter_id = it["iteration_id"]
        loop.approve_iteration(iter_id)
        res = loop.run_iteration(iter_id, allow_unconfigured_dates=True)
        self.assertEqual(res["status"], STATE_FAILED)

    # TEST 12: Zero-data detection
    def test_12_zero_data_detection(self):
        """Test zero-data (0 bars, 0 ticks) maps to INFRASTRUCTURE_FAILURE."""
        mock_audit = {
            "status": STATUS_INVALID,
            "tester_execution_check": {
                "status": "FAIL",
                "bars": 0,
                "ticks": 0,
                "trades": 0,
                "zero_data": True,
                "issues": ["Zero market data processed."],
            },
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
        }
        dec = evaluate_research_decision(mock_audit)
        self.assertEqual(dec["decision"], DECISION_INFRASTRUCTURE_FAILURE)
        self.assertIn("zero market data", dec["reasons"][0].lower())

    # TEST 13: Zero-trade handling
    def test_13_zero_trade_handling(self):
        """Test that zero trades (bars > 0, ticks > 0) is recognized as INSUFFICIENT evidence, not bad strategy."""
        mock_audit = {
            "status": STATUS_PASS,
            "evidence_grade": GRADE_LIMITED,
            "infrastructure_evidence": GRADE_STRONG,
            "trading_performance_evidence": GRADE_INSUFFICIENT,
            "tester_execution_check": {
                "status": "PASS",
                "bars": 2120,
                "ticks": 125602,
                "trades": 0,
                "zero_data": False,
            },
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
            "dataset_check": {"status": "UNCONFIGURED", "dataset_type": "TRAINING"},
        }
        plan = {
            "expected_observations": ["total_trades > 0"],
            "baseline": {"symbol": "GBPUSD", "timeframe": "M15"},
        }
        dec = evaluate_research_decision(mock_audit, plan=plan)
        self.assertEqual(dec["decision"], DECISION_REVISE_PLAN)
        # Check rule note: zero trades must NOT be interpreted as bad strategy performance
        joined_reasons = " ".join(dec["reasons"])
        self.assertIn("not be interpreted as 'bad strategy performance'", joined_reasons.lower())
        self.assertIn("insufficient", joined_reasons.lower())

    # TEST 14: Audit failure
    def test_14_audit_failure(self):
        """Test that an INVALID audit status triggers NEEDS_HUMAN_REVIEW."""
        mock_audit = {
            "status": STATUS_INVALID,
            "tester_execution_check": {"status": "PASS", "bars": 100, "ticks": 500, "trades": 1, "zero_data": False},
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "experiment_identity_check": {"status": "FAIL", "details": "Corrupted ID format"},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
        }
        dec = evaluate_research_decision(mock_audit)
        self.assertEqual(dec["decision"], DECISION_NEEDS_HUMAN_REVIEW)

    # TEST 15: Dataset unconfigured
    def test_15_dataset_unconfigured(self):
        """Test unconfigured research periods are explicitly reported in decision artifact."""
        unconfigured_path = self.config_dir / "unconfigured_periods.json"
        unconfigured_path.write_text(json.dumps({
            "schema_version": 1,
            "status": "unconfigured",
            "periods": {
                "training": {"from": None, "to": None},
                "validation": {"from": None, "to": None},
                "unseen": {"from": None, "to": None},
            }
        }), encoding="utf-8")
        mock_audit = {
            "status": STATUS_PASS,
            "evidence_grade": GRADE_LIMITED,
            "infrastructure_evidence": GRADE_STRONG,
            "trading_performance_evidence": GRADE_INSUFFICIENT,
            "tester_execution_check": {"status": "PASS", "bars": 2120, "ticks": 125602, "trades": 0, "zero_data": False},
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
            "dataset_check": {"status": "UNCONFIGURED", "dataset_type": "TRAINING"},
        }
        dec = evaluate_research_decision(mock_audit, research_periods_path=unconfigured_path)
        self.assertEqual(dec["dataset_discipline"]["status"], "unconfigured")
        self.assertFalse(dec["dataset_discipline"]["periods_configured"])
        self.assertIn("unconfigured placeholders", dec["dataset_discipline"]["note"])

    # TEST 16: Hash mismatch
    def test_16_hash_mismatch(self):
        """Test corrupted cryptographic hash is classified as NEEDS_HUMAN_REVIEW."""
        mock_audit = {
            "status": STATUS_INVALID,
            "artifact_integrity_check": {
                "status": "FAIL",
                "hashes_verified": False,
                "issues": ["SHA-256 hash mismatch for source_after.mq5."],
            },
            "tester_execution_check": {"status": "PASS", "bars": 1000, "ticks": 5000, "trades": 0, "zero_data": False},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
        }
        dec = evaluate_research_decision(mock_audit)
        self.assertEqual(dec["decision"], DECISION_NEEDS_HUMAN_REVIEW)
        self.assertIn("cryptographic hash mismatch", dec["reasons"][0].lower())

    # TEST 17: Decision generation & forbidden words
    def test_17_decision_generation(self):
        """Test decision artifact generation and absence of forbidden words."""
        mock_audit = {
            "status": STATUS_PASS,
            "evidence_grade": GRADE_STRONG,
            "infrastructure_evidence": GRADE_STRONG,
            "trading_performance_evidence": GRADE_ADEQUATE,
            "tester_execution_check": {"status": "PASS", "bars": 5000, "ticks": 200000, "trades": 15, "zero_data": False},
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "change_scope_check": {"status": "PASS"},
            "plan_compliance_check": {"status": "COMPLIANT"},
            "dataset_check": {"status": "CONFIGURED", "dataset_type": "TRAINING"},
        }
        periods_cfg = {
            "schema_version": 1,
            "status": "configured",
            "periods": {
                "training": {"from": "2024.01.01", "to": "2024.02.01"},
            },
        }
        dec = evaluate_research_decision(mock_audit, periods_config=periods_cfg)
        self.assertEqual(dec["decision"], DECISION_CONTINUE_RESEARCH)
        self.assertIsNotNone(dec["next_action"])
        self.assertIsNotNone(dec["recommended_hypothesis_direction"])

        # Check safety invariants: no forbidden words in output
        serialized = json.dumps(dec).lower()
        for forbidden in FORBIDDEN_WORDS:
            self.assertNotIn(forbidden, serialized)

        # Human-readable formatting check
        text = format_human_readable_decision(dec)
        self.assertIn("CONTINUE_RESEARCH", text)

    # TEST 18: Iteration artifact persistence
    def test_18_iteration_artifact_persistence(self):
        """Test that all 8 artifacts are persisted in research/iterations/ITER-XXXX/."""
        it = self.loop.create_iteration(question="Artifact persistence test?", baseline_id="EXP-0002")
        iter_id = it["iteration_id"]
        iter_dir = self.iterations_dir / iter_id

        self.assertTrue((iter_dir / "iteration.json").is_file())
        self.assertTrue((iter_dir / "hypothesis.json").is_file())
        self.assertTrue((iter_dir / "plan.json").is_file())
        self.assertTrue((iter_dir / "approval.json").is_file())

        # Validate iteration.json schema
        data = json.loads((iter_dir / "iteration.json").read_text(encoding="utf-8"))
        is_valid, issues = validate_iteration_dict(data)
        self.assertTrue(is_valid, f"Issues: {issues}")

    # TEST 19: Baseline immutability
    def test_19_baseline_immutability(self):
        """Verify baseline ea/TestEA.mq5 hash is strictly identical after loop operations."""
        it = self.loop.create_iteration(question="Baseline immutability test?", baseline_id="EXP-0002")
        iter_id = it["iteration_id"]
        self.loop.approve_iteration(iter_id)

        # Verify hash of TestEA.mq5 before and after
        current_hash = hashlib.sha256(self.ea_file.read_bytes()).hexdigest()
        self.assertEqual(current_hash, self.ea_hash_before)

    # TEST 20: Complete successful orchestration using mocks
    def test_20_complete_successful_orchestration(self):
        """Test complete end-to-end research loop execution: HYP -> PLAN -> CAND -> EXP -> AUD -> ITER."""
        # 1. Prepare plan with non-trade expected observation (smoke test style)
        plan_data = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0020",
            "hypothesis_id": "HYP-0020",
            "created_at": "2026-09-30T00:00:00+01:00",
            "title": "Smoke Test Orchestration Plan",
            "research_question": "Does the research loop execute end-to-end?",
            "objective": "Verify complete research loop orchestration.",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            },
            "dataset": {"type": "training", "from": "2024.01.01", "to": "2024.02.01"},
            "changes_under_test": [
                {
                    "variable": "FastMAPeriod",
                    "baseline_value": "10",
                    "target_value": "5",
                    "change_type": "parameter_adjustment",
                }
            ],
            "unchanged_variables": [{"variable": "SlowMAPeriod", "value": "20"}],
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "observations": ["Candidate code is generated and compiled cleanly."],
            "expected_observations": ["Candidate code is generated and compiled cleanly."],
            "falsification_conditions": ["Candidate compilation fails."],
            "human_review_required": True,
            "status": "planned",
        }
        (self.plans_dir / "PLAN-0020.json").write_text(json.dumps(plan_data, indent=2))

        # Setup mock MT5 launcher that outputs a valid report
        def mock_launcher(cmd, timeout):
            # Locate output report name from config or cmd
            rep_path = self.mt5_data_dir / "CAND-0001_report.htm"
            rep_content = """<html><body>
            <div align=center><b>Strategy Tester Report</b></div>
            <table>
            <tr><td>Expert:</td><td><b>Candidates\\CAND-0001</b></td></tr>
            <tr><td>Symbol:</td><td><b>GBPUSD</b></td></tr>
            <tr><td>Period:</td><td><b>M15</b></td></tr>
            <tr><td>Bars:</td><td><b>2120</b></td></tr>
            <tr><td>Ticks:</td><td><b>125602</b></td></tr>
            <tr><td>Total Trades:</td><td><b>0</b></td></tr>
            <tr><td>Total Net Profit:</td><td><b>0.00</b></td></tr>
            <tr><td>Gross Profit:</td><td><b>0.00</b></td></tr>
            <tr><td>Gross Loss:</td><td><b>0.00</b></td></tr>
            <tr><td>Profit Factor:</td><td><b>0.00</b></td></tr>
            <tr><td>Maximal Drawdown:</td><td><b>0.00 (0.00%)</b></td></tr>
            <tr><td>History Quality:</td><td><b>100%</b></td></tr>
            </table>
            </body></html>"""
            rep_path.write_bytes(rep_content.encode("utf-16le"))
            return {"exit_code": 0, "timeout": False}

        loop = ResearchLoop(
            iterations_dir=self.iterations_dir,
            hypotheses_dir=self.hypotheses_dir,
            plans_dir=self.plans_dir,
            candidates_dir=self.candidates_dir,
            experiments_dir=self.experiments_dir,
            audits_dir=self.audits_dir,
            ea_dir=self.ea_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=mock_launcher,
        )

        # 1. Create iteration
        it = loop.create_iteration(plan_id="PLAN-0020")
        iter_id = it["iteration_id"]
        self.assertEqual(it["status"], STATE_AWAITING_APPROVAL)

        # 2. Approve iteration
        approved = loop.approve_iteration(iter_id, reviewer="Lead Researcher", note="Smoke test approved")
        self.assertEqual(approved["status"], STATE_APPROVED)
        self.assertEqual(approved["approval_status"], APPROVAL_APPROVED)

        # 3. Execute iteration
        completed = loop.run_iteration(iter_id, mock=True, allow_unconfigured_dates=True)
        self.assertEqual(completed["status"], STATE_COMPLETED)
        self.assertIsNotNone(completed["completed_at"])
        self.assertIsNotNone(completed["candidate_id"])
        self.assertIsNotNone(completed["experiment_id"])
        self.assertIsNotNone(completed["audit_id"])
        self.assertIsNotNone(completed["decision"])

        # 4. Verify complete provenance chain
        self.assertEqual(completed["provenance"]["plan"], "PLAN-0020")
        self.assertEqual(completed["provenance"]["candidate"], completed["candidate_id"])
        self.assertEqual(completed["provenance"]["experiment"], completed["experiment_id"])
        self.assertEqual(completed["provenance"]["audit"], completed["audit_id"])

        # 5. Verify all iteration artifacts exist in memory folder
        iter_dir = self.iterations_dir / iter_id
        for artifact_name in [
            "iteration.json",
            "plan.json",
            "approval.json",
            "candidate.json",
            "experiment.json",
            "audit.json",
            "decision.json",
        ]:
            self.assertTrue(
                (iter_dir / artifact_name).is_file(),
                f"Missing artifact: {artifact_name}",
            )

        # 6. Verify human-readable reporting
        rep_text = format_human_readable_iteration(completed)
        self.assertIn("STATE_COMPLETED" if "STATE_COMPLETED" in rep_text else "COMPLETED", rep_text)
        self.assertIn(completed["experiment_id"], rep_text)


if __name__ == "__main__":
    unittest.main()
