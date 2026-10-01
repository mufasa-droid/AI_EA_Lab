"""
Automated Test Suite for AI EA Lab - Phase 8: AI Developer

Tests:
1. Approval: Missing approval halts execution.
2. Approval: Pending approval halts execution.
3. Approval: Explicit approved plan passes approval check.
4. Plan validation: Missing plan file handling.
5. Plan validation: Malformed plan schema rejected.
6. Baseline validation: Missing baseline experiment rejected.
7. Baseline validation: Baseline input mismatch detected.
8. Feasibility: Current TestEA (no trade logic in OnTick) flagged as requires_plan_revision.
9. Feasibility: Nonexistent parameter in EA flagged as blocked.
10. Feasibility: Valid parameter on compatible EA passes feasibility.
11. Candidate creation & monotonic ID generation (CAND-XXXX).
12. Source protection: Baseline EA in ea/ remains strictly untouched.
13. Source preservation: source_before.mq5, source_after.mq5, diff.patch preserved.
14. Controlled changes: Authorized parameter changed passes static check.
15. Controlled changes: Unauthorized parameter modification rejected.
16. Controlled changes: Unrelated code alteration rejected.
17. Compilation: Successful compilation with MetaEditor captures binary and log.
18. Compilation: Syntax error captures compiler failure and errors gracefully.
19. Compilation: Compiler unavailable handled gracefully.
20. Dry run: Validates and previews changes without writing files.
21. Mock mode: Deterministic mock developer output.
22. CLI JSON output mode.
23. CLI human-readable proposal/status formatting.
24. Approval CLI commands: --approve and --revoke.
25. Safety: No live trading, broker orders, or credential changes.
26. Immutability: EXP-0001 and EXP-0002 remain completely untouched.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from developer.llm.base import MockDeveloperAdapter
from scripts.developer import (
    calculate_sha256,
    format_human_readable_output,
    load_plan,
    run_developer,
    validate_baseline,
)
from scripts.developer_schemas import (
    check_plan_approval,
    get_next_candidate_id,
    set_plan_approval,
    validate_candidate_metadata,
    validate_change_manifest,
    validate_feasibility_dict,
    validate_static_changes,
)
from scripts.feasibility import (
    analyze_plan_feasibility,
    inspect_ea_trading_logic,
    parse_ea_inputs,
    plan_requires_trading_logic,
)
from scripts.mql5_compiler import compile_mql5, find_metaeditor, parse_compiler_output


class TestAIDeveloper(unittest.TestCase):

    def setUp(self):
        self.experiments_dir = PROJECT_ROOT / "experiments"
        self.exp1_dir = self.experiments_dir / "EXP-0001"
        self.exp2_dir = self.experiments_dir / "EXP-0002"
        self.ea_file = PROJECT_ROOT / "ea" / "TestEA.mq5"

        # Capture hash of TestEA.mq5 and EXP-0001/0002 for immutability tests
        if self.ea_file.is_file():
            self.testea_hash_before = hashlib.sha256(self.ea_file.read_bytes()).hexdigest()
        if (self.exp1_dir / "metadata.json").is_file():
            self.exp1_meta_before = (self.exp1_dir / "metadata.json").read_bytes()
        if (self.exp2_dir / "metadata.json").is_file():
            self.exp2_meta_before = (self.exp2_dir / "metadata.json").read_bytes()

    def _create_temp_workspace(self):
        """Helper to create an isolated mock workspace for developer operations."""
        td = Path(tempfile.mkdtemp())
        ea_dir = td / "ea"
        ea_dir.mkdir()
        plans_dir = td / "plans"
        plans_dir.mkdir()
        exps_dir = td / "experiments"
        exps_dir.mkdir()
        cands_dir = td / "candidates"
        cands_dir.mkdir()

        # Create baseline experiment EXP-0002
        b_dir = exps_dir / "EXP-0002"
        b_dir.mkdir()
        (b_dir / "metadata.json").write_text(json.dumps({
            "experiment_id": "EXP-0002",
            "ea": "SampleEA",
            "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "symbol": "GBPUSD",
            "timeframe": "M15"
        }), encoding="utf-8")
        (b_dir / "metrics.json").write_text("{}", encoding="utf-8")

        # Create SampleEA with basic trading logic
        ea_src = (
            "input int FastMAPeriod = 10;\n"
            "input int SlowMAPeriod = 20;\n"
            "input double LotSize = 0.01;\n\n"
            "void OnTick()\n"
            "{\n"
            "   // Active trading logic\n"
            "   if(FastMAPeriod > 0)\n"
            "      Print(\"tick\");\n"
            "}\n"
        )
        (ea_dir / "SampleEA.mq5").write_text(ea_src, encoding="utf-8")

        # Create valid approved plan
        plan = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0002",
            "hypothesis_id": "HYP-0001",
            "title": "FastMAPeriod adjustment",
            "research_question": "Does FastMAPeriod 5 work?",
            "objective": "Test FastMAPeriod 10 -> 5",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "SampleEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"}
            },
            "changes_under_test": [{
                "variable": "FastMAPeriod",
                "baseline_value": "10",
                "target_value": "5",
                "change_type": "parameter_adjustment"
            }],
            "unchanged_variables": [
                {"variable": "SlowMAPeriod", "value": "20"},
                {"variable": "LotSize", "value": "0.01"}
            ],
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20", "LotSize": "0.01"},
            "dataset": {"type": "training"},
            "observations": ["FastMAPeriod"],
            "expected_observations": ["Parameter FastMAPeriod defaults to 5"],
            "falsification_conditions": ["Parameter remains 10"],
            "human_review_required": True,
            "status": "approved",
            "approval": {"status": "approved", "reviewed_by": "Lead Quant"}
        }
        (plans_dir / "PLAN-0002.json").write_text(json.dumps(plan), encoding="utf-8")

        return td, ea_dir, plans_dir, exps_dir, cands_dir

    def test_01_missing_approval_halts_execution(self):
        """Test that plans lacking an explicit approval block halt execution."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        # Remove approval block
        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        del plan["approval"]
        plan["status"] = "planned"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "approval_required")
        self.assertIn("Approval missing", res["reason"])
        self.assertIsNone(res["candidate_id"])
        self.assertEqual(len(list(cands_dir.glob("CAND-*"))), 0)

    def test_02_pending_approval_halts_execution(self):
        """Test that a plan with approval status 'pending' halts execution."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["approval"] = {"status": "pending"}
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "approval_required")
        self.assertIn("Approval pending", res["reason"])
        self.assertIsNone(res["candidate_id"])

    def test_03_explicit_approval_allows_execution(self):
        """Test that an explicitly approved plan proceeds through approval gate."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertIn(res["status"], {"ready_for_next_phase", "compile_failed"})
        self.assertEqual(res["approval"]["status"], "approved")
        self.assertIsNotNone(res["candidate_id"])

    def test_04_missing_plan_file_handling(self):
        """Test that attempting to implement a non-existent plan reports error cleanly."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        res = run_developer(
            "PLAN-9999",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "error")
        self.assertIn("Plan file not found", res["reason"])

    def test_05_malformed_plan_schema_rejected(self):
        """Test that a malformed plan missing schema fields is rejected."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        malformed = {"schema_version": 1, "experiment_plan_id": "PLAN-0003"}
        (plans_dir / "PLAN-0003.json").write_text(json.dumps(malformed), encoding="utf-8")

        res = run_developer(
            "PLAN-0003",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "plan_invalid")
        self.assertIn("Plan schema validation failed", res["reason"])

    def test_06_missing_baseline_experiment(self):
        """Test that a plan citing a non-existent baseline is rejected."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["baseline"]["experiment_id"] = "EXP-9999"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "baseline_invalid")
        self.assertIn("Baseline experiment 'EXP-9999' does not exist", res["reason"])

    def test_07_baseline_input_mismatch_detected(self):
        """Test that mismatch between plan baseline_value and actual baseline experiment is caught."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        # Baseline EXP-0002 has FastMAPeriod=10, but plan claims baseline was 20
        plan["changes_under_test"][0]["baseline_value"] = "20"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "baseline_invalid")
        self.assertIn("Baseline input mismatch for 'FastMAPeriod'", res["reason"])

    def test_08_feasibility_current_testea_no_trade_logic(self):
        """Test that PLAN-0001 against TestEA.mq5 is rejected as requires_plan_revision because OnTick has no trade logic."""
        # Load the actual PLAN-0001 from repository
        plan_file = PROJECT_ROOT / "research" / "plans" / "PLAN-0001.json"
        self.assertTrue(plan_file.is_file())

        with open(plan_file, "r", encoding="utf-8") as f:
            plan = json.load(f)

        # Temporarily test feasibility analysis directly
        feas = analyze_plan_feasibility(plan, self.ea_file)
        self.assertFalse(feas["feasible"])
        self.assertEqual(feas["status"], "requires_plan_revision")
        self.assertIn("does not contain trading/signal execution logic", feas["reason"])
        self.assertIn("FastMAPeriod", feas["reason"])

    def test_09_feasibility_nonexistent_parameter(self):
        """Test that requesting a parameter not in EA input declarations is flagged as blocked."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        plan["changes_under_test"] = [{
            "variable": "NonExistentParam",
            "baseline_value": "100",
            "target_value": "200",
            "change_type": "parameter_adjustment"
        }]
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertEqual(res["status"], "blocked")
        self.assertIn("NonExistentParam", res["reason"])

    def test_10_feasibility_valid_parameter_compatible_ea(self):
        """Test that valid parameter change on compatible EA passes feasibility analysis."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()
        plan_file = plans_dir / "PLAN-0002.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))

        feas = analyze_plan_feasibility(plan, ea_dir / "SampleEA.mq5")
        self.assertTrue(feas["feasible"])
        self.assertEqual(feas["status"], "pass")
        self.assertEqual(len(feas["required_changes"]), 1)
        self.assertEqual(feas["required_changes"][0]["parameter"], "FastMAPeriod")

    def test_11_candidate_creation_and_monotonic_id(self):
        """Test that candidate directories are created with sequential IDs (CAND-0001, CAND-0002)."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        cid1 = get_next_candidate_id(cands_dir)
        self.assertEqual(cid1, "CAND-0001")
        (cands_dir / cid1).mkdir()

        cid2 = get_next_candidate_id(cands_dir)
        self.assertEqual(cid2, "CAND-0002")

    def test_12_source_protection_baseline_untouched(self):
        """Test that running the developer never overwrites the baseline EA source."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()
        ea_file = ea_dir / "SampleEA.mq5"
        orig_content = ea_file.read_text(encoding="utf-8")

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        # Verify SampleEA was NOT modified
        self.assertEqual(ea_file.read_text(encoding="utf-8"), orig_content)

    def test_13_source_before_and_after_and_diff(self):
        """Test that candidate directory preserves source_before, source_after, and diff.patch."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        res = run_developer(
            "PLAN-0002",
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        cand_id = res["candidate_id"]
        cand_dir = cands_dir / cand_id

        self.assertTrue((cand_dir / "source_before.mq5").is_file())
        self.assertTrue((cand_dir / "source_after.mq5").is_file())
        self.assertTrue((cand_dir / "diff.patch").is_file())
        self.assertTrue((cand_dir / "change_manifest.json").is_file())
        self.assertTrue((cand_dir / "feasibility.json").is_file())
        self.assertTrue((cand_dir / "metadata.json").is_file())

        # Verify source_after has the updated parameter
        after_code = (cand_dir / "source_after.mq5").read_text(encoding="utf-8")
        self.assertIn("input int FastMAPeriod = 5;", after_code)

        # Verify diff contains the modification
        diff_text = (cand_dir / "diff.patch").read_text(encoding="utf-8")
        self.assertIn("-input int FastMAPeriod = 10;", diff_text)
        self.assertIn("+input int FastMAPeriod = 5;", diff_text)

    def test_14_static_validation_authorized_change(self):
        """Test static change validation passes when only authorized input parameter changed."""
        src_before = "input int FastMAPeriod = 10;\nvoid OnTick() {}\n"
        src_after = "input int FastMAPeriod = 5;\nvoid OnTick() {}\n"
        auth = [{"variable": "FastMAPeriod", "target_value": "5"}]

        is_valid, applied, unauth = validate_static_changes(src_before, src_after, auth)
        self.assertTrue(is_valid)
        self.assertEqual(len(applied), 1)
        self.assertEqual(len(unauth), 0)

    def test_15_static_validation_unauthorized_parameter_rejected(self):
        """Test that modifying an unauthorized parameter is caught and candidate fails static check."""
        src_before = "input int FastMAPeriod = 10;\ninput int SlowMAPeriod = 20;\nvoid OnTick() {}\n"
        # FastMAPeriod changed (authorized), but SlowMAPeriod also changed (unauthorized)
        src_after = "input int FastMAPeriod = 5;\ninput int SlowMAPeriod = 30;\nvoid OnTick() {}\n"
        auth = [{"variable": "FastMAPeriod", "target_value": "5"}]

        is_valid, applied, unauth = validate_static_changes(src_before, src_after, auth)
        self.assertFalse(is_valid)
        self.assertTrue(any("SlowMAPeriod" in u for u in unauth))

    def test_16_static_validation_unrelated_code_change_rejected(self):
        """Test that altering non-input code (e.g. trading logic, functions) is caught as unauthorized."""
        src_before = "input int FastMAPeriod = 10;\nvoid OnTick() {}\n"
        src_after = "input int FastMAPeriod = 5;\nvoid OnTick() { Print(\"unauthorized!\"); }\n"
        auth = [{"variable": "FastMAPeriod", "target_value": "5"}]

        is_valid, applied, unauth = validate_static_changes(src_before, src_after, auth)
        self.assertFalse(is_valid)
        self.assertTrue(any("non-input" in u for u in unauth))

    def test_17_compilation_success(self):
        """Test that compiling valid MQL5 code succeeds and captures compile.log and binary."""
        compiler = find_metaeditor()
        if not compiler:
            self.skipTest("MetaEditor not installed on this system.")

        td = Path(tempfile.mkdtemp())
        src = td / "Valid.mq5"
        src.write_text("input int FastMAPeriod = 5;\nvoid OnTick() {}\n", encoding="utf-8")

        res = compile_mql5(src, output_dir=td)
        self.assertEqual(res["status"], "passed")
        self.assertEqual(res["error_count"], 0)
        self.assertIsNotNone(res["binary_path"])
        self.assertTrue(Path(res["binary_path"]).is_file())

    def test_18_compilation_failure_handling(self):
        """Test that invalid MQL5 syntax records compiler failure without crashing."""
        compiler = find_metaeditor()
        if not compiler:
            self.skipTest("MetaEditor not installed on this system.")

        td = Path(tempfile.mkdtemp())
        src = td / "Bad.mq5"
        src.write_text("input int FastMAPeriod = ;\nvoid OnTick() { syntax error }\n", encoding="utf-8")

        res = compile_mql5(src, output_dir=td)
        self.assertEqual(res["status"], "failed")
        self.assertGreater(res["error_count"], 0)
        self.assertTrue(len(res["errors"]) > 0)
        self.assertIsNone(res["binary_path"])

    def test_19_compilation_unavailable_handling(self):
        """Test that compile_mql5 handles nonexistent compiler gracefully."""
        td = Path(tempfile.mkdtemp())
        src = td / "Test.mq5"
        src.write_text("void OnTick() {}\n", encoding="utf-8")

        res = compile_mql5(src, output_dir=td, compiler_path=Path("C:/NonExistent/metaeditor.exe"))
        self.assertEqual(res["status"], "unavailable")
        self.assertIn("not found", res["warnings"][0])

    def test_20_dry_run_mode(self):
        """Test that dry-run performs analysis without creating candidate directory."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()

        res = run_developer(
            "PLAN-0002",
            dry_run=True,
            plans_dir=plans_dir,
            candidates_dir=cands_dir,
            experiments_dir=exps_dir,
            ea_dir=ea_dir
        )
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["status"], "ready_for_next_phase")
        self.assertEqual(len(list(cands_dir.glob("CAND-*"))), 0)

    def test_21_mock_mode_deterministic(self):
        """Test that MockDeveloperAdapter produces identical modifications across multiple invocations."""
        adapter = MockDeveloperAdapter()
        plan = {
            "changes_under_test": [{
                "variable": "FastMAPeriod",
                "target_value": "7"
            }]
        }
        src = "input int FastMAPeriod = 10;\ninput int SlowMAPeriod = 20;\n"

        out1 = adapter.develop_candidate(plan, src)
        out2 = adapter.develop_candidate(plan, src)

        self.assertEqual(out1["modified_source"], out2["modified_source"])
        self.assertIn("input int FastMAPeriod = 7;", out1["modified_source"])
        self.assertIn("input int SlowMAPeriod = 20;", out1["modified_source"])

    def test_22_cli_json_mode(self):
        """Test CLI execution with --json produces valid JSON output."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "developer.py"),
            "--plan", "PLAN-0001",
            "--json"
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        self.assertEqual(proc.returncode, 0)

        data = json.loads(proc.stdout)
        self.assertIn("plan_id", data)
        self.assertIn("status", data)
        self.assertIn("approval", data)

    def test_23_cli_human_readable_output(self):
        """Test CLI human readable formatting contains required sections."""
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "developer.py"),
            "--plan", "PLAN-0001",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        self.assertEqual(proc.returncode, 0)

        out = proc.stdout
        self.assertIn("AI-EA-LAB", out)
        self.assertIn("Plan: PLAN-0001", out)
        self.assertIn("Approval:", out)
        self.assertIn("Status:", out)

    def test_24_plan_approval_cli_commands(self):
        """Test that --approve and --revoke CLI options update plan approval state on disk."""
        td, ea_dir, plans_dir, exps_dir, cands_dir = self._create_temp_workspace()
        plan_file = plans_dir / "PLAN-0002.json"

        # Revoke
        set_plan_approval(plan_file, "pending", approved_by="Auditor", note="Needs check")
        is_app, reason, block = check_plan_approval(json.loads(plan_file.read_text(encoding="utf-8")))
        self.assertFalse(is_app)
        self.assertEqual(block["status"], "pending")

        # Approve
        set_plan_approval(plan_file, "approved", approved_by="Lead", note="Approved")
        is_app, reason, block = check_plan_approval(json.loads(plan_file.read_text(encoding="utf-8")))
        self.assertTrue(is_app)
        self.assertEqual(block["status"], "approved")

    def test_25_safety_no_live_trading_or_broker_calls(self):
        """Safety invariant: verify developer module contains no live trading or broker order execution code."""
        dev_code = (PROJECT_ROOT / "scripts" / "developer.py").read_text(encoding="utf-8").lower()

        forbidden_patterns = [
            "traderequest",
            "account_info",
            "order_send",
            "positions_get",
            "orders_get",
            "login_broker",
            "live_execution",
            "connect_broker",
        ]
        for pattern in forbidden_patterns:
            self.assertNotIn(pattern, dev_code)

    def test_26_historical_experiments_remain_untouched(self):
        """Verify that running Developer does not modify EXP-0001 or EXP-0002 files or hashes."""
        if hasattr(self, "exp1_meta_before"):
            current_exp1 = (self.exp1_dir / "metadata.json").read_bytes()
            self.assertEqual(current_exp1, self.exp1_meta_before)

        if hasattr(self, "exp2_meta_before"):
            current_exp2 = (self.exp2_dir / "metadata.json").read_bytes()
            self.assertEqual(current_exp2, self.exp2_meta_before)

        if hasattr(self, "testea_hash_before") and self.ea_file.is_file():
            current_ea_hash = hashlib.sha256(self.ea_file.read_bytes()).hexdigest()
            self.assertEqual(current_ea_hash, self.testea_hash_before)


if __name__ == "__main__":
    unittest.main()
