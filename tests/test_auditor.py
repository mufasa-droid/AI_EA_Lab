"""
Automated Test Suite for AI EA Lab - Phase 10: AI Auditor

Tests:
1. Valid experiment audit (EXP-0004 real artifact).
2. Canonical baseline experiment audit (EXP-0002).
3. Missing experiment handling (returns INVALID).
4. Broken provenance detection (missing plan/candidate).
5. Candidate / report identity mismatch detection.
6. Zero-data report handling (0 bars, 0 ticks -> INVALID).
7. Zero-trade valid data distinction (bars > 0, ticks > 0, trades = 0 -> PASS).
8. Corrupted cryptographic hash detection.
9. Missing report artifact handling.
10. Missing metrics artifact handling.
11. Plan compliance mismatch detection (NON_COMPLIANT).
12. Unauthorized candidate change detection.
13. Unconfigured dataset detection.
14. Configured dataset handling.
15. Overfitting risk evaluation.
16. Data leakage risk evaluation.
17. Robustness concerns documentation.
18. Reproducibility evaluation.
19. Strict separation of Facts vs Interpretations.
20. Deterministic mock auditor execution.
21. Audit immutability and persistence.
22. CLI JSON output validity.
23. CLI human-readable formatting.
24. Safety Invariant: No ranking, no "winner" declaration, no scoreboards.
25. Safety Invariant: No live trading, broker order execution, or credential modifications.
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

from auditor.llm.base import BaseAuditorAdapter, MockAuditorAdapter
from scripts.auditor import (
    audit_artifact_integrity,
    audit_change_scope,
    audit_dataset,
    audit_experiment_identity,
    audit_plan_compliance,
    audit_provenance,
    audit_report_consistency,
    audit_reproducibility,
    audit_tester_execution,
    format_human_readable_audit,
    run_audit,
)
from scripts.auditor_schemas import (
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_NON_COMPLIANT,
    COMPLIANCE_NOT_APPLICABLE,
    FORBIDDEN_WORDS,
    GRADE_ADEQUATE,
    GRADE_INSUFFICIENT,
    GRADE_LIMITED,
    GRADE_STRONG,
    STATUS_INVALID,
    STATUS_NEEDS_REVIEW,
    STATUS_PASS,
    get_next_audit_id,
    validate_audit_dict,
)


class TestAIAuditor(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.experiments_dir = self.temp_dir / "experiments"
        self.candidates_dir = self.temp_dir / "developer" / "candidates"
        self.plans_dir = self.temp_dir / "research" / "plans"
        self.hypotheses_dir = self.temp_dir / "research" / "hypotheses"
        self.audits_dir = self.temp_dir / "audits"
        self.config_dir = self.temp_dir / "config"

        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.hypotheses_dir.mkdir(parents=True, exist_ok=True)
        self.audits_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Create research_periods.json (unconfigured placeholder)
        self.research_periods_path = self.config_dir / "research_periods.json"
        self.research_periods_path.write_text(
            json.dumps({
                "schema_version": 1,
                "status": "unconfigured",
                "periods": {
                    "training": {"from": None, "to": None},
                    "validation": {"from": None, "to": None},
                    "unseen": {"from": None, "to": None},
                }
            }, indent=2),
            encoding="utf-8"
        )

        # Setup mock candidate CAND-0001
        self.cand_dir = self.candidates_dir / "CAND-0001"
        self.cand_dir.mkdir(parents=True, exist_ok=True)
        self.src_after = "// Candidate MQL5\ninput int FastMAPeriod = 5;\n"
        self.src_after_path = self.cand_dir / "source_after.mq5"
        self.src_after_path.write_bytes(self.src_after.encode("utf-8"))
        self.src_after_sha = hashlib.sha256(self.src_after_path.read_bytes()).hexdigest()

        self.bin_after_path = self.cand_dir / "source_after.ex5"
        self.bin_after_path.write_bytes(b"\x00\x01\x02\x03\x04")
        self.bin_after_sha = hashlib.sha256(b"\x00\x01\x02\x03\x04").hexdigest()

        (self.cand_dir / "metadata.json").write_text(
            json.dumps({
                "candidate_id": "CAND-0001",
                "plan_id": "PLAN-0002",
                "hypothesis_id": "HYP-0001",
                "baseline_experiment": "EXP-0002",
                "source_after_sha256": self.src_after_sha,
                "status": "ready_for_next_phase",
            }, indent=2),
            encoding="utf-8"
        )

        (self.cand_dir / "change_manifest.json").write_text(
            json.dumps({
                "candidate_id": "CAND-0001",
                "changes": [{"parameter": "FastMAPeriod", "before": "10", "after": "5"}],
                "unauthorized_changes": [],
            }, indent=2),
            encoding="utf-8"
        )

        # Setup mock plan PLAN-0002
        (self.plans_dir / "PLAN-0002.json").write_text(
            json.dumps({
                "experiment_plan_id": "PLAN-0002",
                "hypothesis_id": "HYP-0001",
                "target_ea": "TestEA",
                "baseline": {
                    "experiment_id": "EXP-0002",
                    "ea": "TestEA",
                    "symbol": "GBPUSD",
                    "timeframe": "M15",
                },
                "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
                "changes_under_test": [{"variable": "FastMAPeriod", "baseline_value": "10", "target_value": "5"}],
                "status": "approved",
            }, indent=2),
            encoding="utf-8"
        )

        # Setup mock baseline EXP-0002
        self.exp2_dir = self.experiments_dir / "EXP-0002"
        self.exp2_dir.mkdir(parents=True, exist_ok=True)
        (self.exp2_dir / "metadata.json").write_text(
            json.dumps({
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "from": "2024.01.01",
                "to": "2024.02.01",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            }, indent=2),
            encoding="utf-8"
        )

        # Setup mock experiment EXP-0004
        self.exp4_dir = self.experiments_dir / "EXP-0004"
        self.exp4_dir.mkdir(parents=True, exist_ok=True)
        (self.exp4_dir / "metadata.json").write_text(
            json.dumps({
                "experiment_id": "EXP-0004",
                "candidate_id": "CAND-0001",
                "plan_id": "PLAN-0002",
                "hypothesis_id": "HYP-0001",
                "baseline_experiment": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "from": "2024.01.01",
                "to": "2024.02.01",
                "dataset": "training",
                "candidate_source_sha256": self.src_after_sha,
                "candidate_ex5_sha256": self.bin_after_sha,
                "backtest_config": {"symbol": "GBPUSD", "timeframe": "M15", "model": 1},
                "inputs": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
                "tester_sync": {
                    "source_hash": self.bin_after_sha,
                    "destination_hash": self.bin_after_sha,
                    "verified": True,
                },
                "status": "COMPLETED",
            }, indent=2),
            encoding="utf-8"
        )
        (self.exp4_dir / "metrics.json").write_text(
            json.dumps({
                "settings": {
                    "expert": "CAND-0001",
                    "symbol": "GBPUSD",
                    "timeframe": "M15",
                    "from": "2024.01.01",
                    "to": "2024.02.01",
                    "inputs": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
                },
                "metrics": {
                    "bars": 2120,
                    "ticks": 125602,
                    "total_trades": 0,
                    "total_net_profit": 0.0,
                    "profit_factor": 0.0,
                },
            }, indent=2),
            encoding="utf-8"
        )
        (self.exp4_dir / "report.htm").write_text(
            "<html><body><table><tr><td>Expert:</td><td><b>CAND-0001</b></td></tr></table></body></html>",
            encoding="utf-8"
        )

        # Setup manifest
        (self.experiments_dir / "manifest.json").write_text(
            json.dumps({
                "total_experiments": 2,
                "experiments": [
                    {"id": "EXP-0002", "total_trades": 0},
                    {"id": "EXP-0004", "total_trades": 0},
                ]
            }, indent=2),
            encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_valid_experiment_audit(self):
        """Test full audit of valid candidate experiment produces PASS and schema compliance."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
        )

        self.assertEqual(audit["status"], STATUS_PASS)
        self.assertEqual(audit["experiment_id"], "EXP-0004")
        self.assertEqual(audit["candidate_id"], "CAND-0001")
        self.assertEqual(audit["infrastructure_evidence"], GRADE_STRONG)
        self.assertEqual(audit["trading_performance_evidence"], GRADE_INSUFFICIENT)
        self.assertEqual(audit["evidence_grade"], GRADE_LIMITED)

        is_valid, issues = validate_audit_dict(audit)
        self.assertTrue(is_valid, f"Schema validation failed: {issues}")

    def test_02_baseline_experiment_audit(self):
        """Test audit of canonical baseline experiment (EXP-0002) handles missing provenance gracefully."""
        (self.exp2_dir / "report.htm").write_text("<html>Report</html>", encoding="utf-8")
        (self.exp2_dir / "metrics.json").write_text(json.dumps({"metrics": {"bars": 2000, "ticks": 100000, "total_trades": 0}}), encoding="utf-8")

        audit = run_audit(
            "EXP-0002",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
        )

        self.assertEqual(audit["status"], STATUS_PASS)
        self.assertEqual(audit["provenance_check"]["status"], "NOT_APPLICABLE")
        self.assertEqual(audit["change_scope_check"]["status"], "NOT_APPLICABLE")

    def test_03_missing_experiment_handling(self):
        """Test that auditing a non-existent experiment returns INVALID without crashing."""
        audit = run_audit(
            "EXP-9999",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
        )
        self.assertEqual(audit["status"], STATUS_INVALID)
        self.assertEqual(audit["evidence_grade"], GRADE_INSUFFICIENT)

    def test_04_broken_provenance_missing_plan(self):
        """Test that experiment pointing to non-existent plan is flagged with broken provenance."""
        # Point to missing plan
        meta_file = self.exp4_dir / "metadata.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["plan_id"] = "PLAN-9999"
        meta_file.write_text(json.dumps(meta), encoding="utf-8")

        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertEqual(audit["provenance_check"]["status"], "FAIL")
        self.assertFalse(audit["provenance_check"]["lineage_intact"])

    def test_05_candidate_report_identity_mismatch(self):
        """Anti-contamination: test that report showing old baseline EA instead of candidate triggers FAIL."""
        # Overwrite report with TestEA instead of CAND-0001
        (self.exp4_dir / "report.htm").write_text(
            "<html><body><table><tr><td>Expert:</td><td><b>TestEA</b></td></tr></table></body></html>",
            encoding="utf-8"
        )
        metrics_file = self.exp4_dir / "metrics.json"
        m = json.loads(metrics_file.read_text(encoding="utf-8"))
        m["settings"]["expert"] = "TestEA"
        metrics_file.write_text(json.dumps(m), encoding="utf-8")

        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertEqual(audit["report_consistency_check"]["status"], "FAIL")
        self.assertEqual(audit["status"], STATUS_INVALID)

    def test_06_zero_data_report_invalid(self):
        """Test that test with 0 bars and 0 ticks is flagged as INVALID."""
        metrics_file = self.exp4_dir / "metrics.json"
        m = json.loads(metrics_file.read_text(encoding="utf-8"))
        m["metrics"]["bars"] = 0
        m["metrics"]["ticks"] = 0
        metrics_file.write_text(json.dumps(m), encoding="utf-8")

        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertEqual(audit["tester_execution_check"]["status"], "INVALID")
        self.assertTrue(audit["tester_execution_check"]["zero_data"])
        self.assertEqual(audit["status"], STATUS_INVALID)

    def test_07_zero_trade_valid_data(self):
        """Test that bars > 0 and ticks > 0 with trades == 0 is valid execution but limited trade evidence."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertEqual(audit["tester_execution_check"]["status"], "PASS")
        self.assertFalse(audit["tester_execution_check"]["zero_data"])
        self.assertEqual(audit["trading_performance_evidence"], GRADE_INSUFFICIENT)

    def test_08_corrupted_hash_detection(self):
        """Test that modified source after metadata record triggers hash verification failure."""
        self.src_after_path.write_text("// Modified unauthorized code", encoding="utf-8")

        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertEqual(audit["artifact_integrity_check"]["status"], "FAIL")
        self.assertFalse(audit["artifact_integrity_check"]["hashes_verified"])
        self.assertEqual(audit["status"], STATUS_NEEDS_REVIEW)

    def test_09_missing_report_artifact(self):
        """Test missing report.htm triggers artifact integrity failure."""
        (self.exp4_dir / "report.htm").unlink()
        res = audit_artifact_integrity(
            self.exp4_dir,
            json.loads((self.exp4_dir / "metadata.json").read_text(encoding="utf-8")),
            {},
            self.experiments_dir / "manifest.json",
            self.candidates_dir,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("report.htm" in issue for issue in res["issues"]))

    def test_10_missing_metrics_artifact(self):
        """Test missing metrics.json triggers artifact integrity failure."""
        (self.exp4_dir / "metrics.json").unlink()
        res = audit_artifact_integrity(
            self.exp4_dir,
            json.loads((self.exp4_dir / "metadata.json").read_text(encoding="utf-8")),
            {},
            self.experiments_dir / "manifest.json",
            self.candidates_dir,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertTrue(any("metrics.json" in issue for issue in res["issues"]))

    def test_11_plan_compliance_mismatch(self):
        """Test that parameter mismatch against approved plan is flagged as NON_COMPLIANT."""
        meta = json.loads((self.exp4_dir / "metadata.json").read_text(encoding="utf-8"))
        # Change actual input parameter to mismatch plan
        meta["inputs"]["FastMAPeriod"] = "99"

        plan = json.loads((self.plans_dir / "PLAN-0002.json").read_text(encoding="utf-8"))
        res = audit_plan_compliance(meta, {"settings": {"inputs": meta["inputs"]}}, plan)

        self.assertEqual(res["status"], COMPLIANCE_NON_COMPLIANT)
        self.assertTrue(any("FastMAPeriod" in dev for dev in res["deviations"]))

    def test_12_unauthorized_candidate_change(self):
        """Test that unauthorized candidate changes are caught in change scope check."""
        (self.cand_dir / "change_manifest.json").write_text(
            json.dumps({
                "candidate_id": "CAND-0001",
                "changes": [],
                "unauthorized_changes": ["Modified OnTick() logic without plan authorization"],
            }, indent=2),
            encoding="utf-8"
        )

        res = audit_change_scope("CAND-0001", self.candidates_dir, {})
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("Modified OnTick() logic without plan authorization", res["unauthorized_changes"])

    def test_13_unconfigured_dataset_handling(self):
        """Test unconfigured research periods are truthfully reported without hallucinating dates."""
        meta = json.loads((self.exp4_dir / "metadata.json").read_text(encoding="utf-8"))
        res = audit_dataset(meta, self.research_periods_path)
        self.assertEqual(res["status"], "UNCONFIGURED")
        self.assertEqual(res["periods_status"], "unconfigured")

    def test_14_configured_dataset_handling(self):
        """Test configured research periods are properly recorded."""
        cfg_path = self.temp_dir / "configured_periods.json"
        cfg_path.write_text(
            json.dumps({
                "schema_version": 1,
                "status": "configured",
                "periods": {
                    "training": {"from": "2024.01.01", "to": "2024.06.01"},
                    "validation": {"from": "2024.06.02", "to": "2024.09.01"},
                    "unseen": {"from": "2024.09.02", "to": "2024.12.31"},
                }
            }, indent=2),
            encoding="utf-8"
        )
        meta = {"dataset": "training"}
        res = audit_dataset(meta, cfg_path)
        self.assertEqual(res["status"], "CONFIGURED")
        self.assertEqual(res["dataset_type"], "TRAINING")

    def test_15_overfitting_risk_evaluation(self):
        """Test overfitting risk evaluation generates structured items."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertIsInstance(audit["overfitting_risks"], list)
        for risk in audit["overfitting_risks"]:
            self.assertIn("risk_type", risk)
            self.assertIn("level", risk)
            self.assertIn(risk["level"], {"OBSERVED", "POSSIBLE", "UNKNOWN"})

    def test_16_data_leakage_risk_evaluation(self):
        """Test data leakage risks state 'Unable to determine' when dataset is unconfigured."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        self.assertIsInstance(audit["data_leakage_risks"], list)
        leakage_descs = " ".join(r["description"] for r in audit["data_leakage_risks"])
        self.assertIn("unable to determine", leakage_descs.lower())

    def test_17_robustness_concerns_documented(self):
        """Test that single-window and zero-trade robustness concerns are explicitly documented."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        concerns = " ".join(audit["robustness_concerns"])
        self.assertIn("zero trades", concerns.lower())

    def test_18_reproducibility_audit(self):
        """Test reproducibility check accurately rates completeness."""
        res_full = audit_reproducibility(self.exp4_dir, {"inputs": {"a": 1}, "backtest_config": {"b": 2}}, "CAND-0001", self.candidates_dir)
        self.assertEqual(res_full["status"], "COMPLETE")
        self.assertTrue(res_full["can_reproduce"])

        # Missing input params
        res_partial = audit_reproducibility(self.exp4_dir, {}, "CAND-0001", self.candidates_dir)
        self.assertNotEqual(res_partial["status"], "COMPLETE")

    def test_19_facts_vs_interpretations_separation(self):
        """Test strict distinction between factual observations and logical interpretations."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        # Observations should report concrete numbers
        obs_text = " ".join(audit["observations"])
        self.assertIn("2,120", obs_text)
        self.assertIn("125,602", obs_text)

        # Interpretations should explain methodological significance
        interp_text = " ".join(audit["interpretations"])
        self.assertIn("no empirical evidence regarding trading strategy", interp_text)

    def test_20_deterministic_mock_auditor(self):
        """Test that running the auditor multiple times produces identical evaluations."""
        adapter = MockAuditorAdapter()
        ctx = {"experiment_id": "EXP-0004", "tester_execution_check": {"bars": 2120, "ticks": 125602, "trades": 0}}
        res1 = adapter.evaluate_evidence(ctx)
        res2 = adapter.evaluate_evidence(ctx)
        self.assertEqual(res1, res2)

    def test_21_audit_immutability_preservation(self):
        """Test that existing audit.json is preserved and returned on subsequent runs unless forced."""
        audit1 = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
        )
        aid1 = audit1["audit_id"]

        audit2 = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=False,
        )
        self.assertEqual(audit2["audit_id"], aid1)

    def test_22_cli_json_mode(self):
        """Test CLI format conforms to schema and produces valid JSON."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        json_str = json.dumps(audit, indent=2)
        parsed = json.loads(json_str)
        is_valid, issues = validate_audit_dict(parsed)
        self.assertTrue(is_valid, f"Issues: {issues}")

    def test_23_cli_human_readable_output(self):
        """Test formatted console output includes all required sections."""
        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        text = format_human_readable_audit(audit)
        self.assertIn("AI-EA-LAB -- AI AUDITOR (PHASE 10)", text)
        self.assertIn("Audit Status:", text)
        self.assertIn("Infrastructure Evidence:", text)
        self.assertIn("Trading Performance Evidence:", text)
        self.assertIn("--- STRUCTURAL CHECKS ---", text)
        self.assertIn("--- FACTS & OBSERVATIONS ---", text)
        self.assertIn("--- INTERPRETATIONS ---", text)
        self.assertIn("--- METHODOLOGICAL RISKS ---", text)

    def test_24_safety_no_ranking_or_winner_declaration(self):
        """Safety invariant: verify no ranking or winner terminology exists in auditor code or output."""
        code = (PROJECT_ROOT / "scripts" / "auditor.py").read_text(encoding="utf-8").lower()
        for forbidden in FORBIDDEN_WORDS:
            self.assertNotIn(forbidden, code)

        audit = run_audit(
            "EXP-0004",
            experiments_dir=self.experiments_dir,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            hypotheses_dir=self.hypotheses_dir,
            audits_dir=self.audits_dir,
            research_periods_path=self.research_periods_path,
            force=True,
        )
        serialized = json.dumps(audit).lower()
        for forbidden in FORBIDDEN_WORDS:
            self.assertNotIn(forbidden, serialized)

    def test_25_safety_no_live_trading_or_broker_calls(self):
        """Safety invariant: verify auditor contains zero order placement or account risk code."""
        code = (PROJECT_ROOT / "scripts" / "auditor.py").read_text(encoding="utf-8").lower()
        forbidden_trading = [
            "ordersend",
            "positionopen",
            "traderequest",
            "account_info",
            "ctrade",
            "login_broker",
        ]
        for term in forbidden_trading:
            self.assertNotIn(term, code)


if __name__ == "__main__":
    unittest.main()
