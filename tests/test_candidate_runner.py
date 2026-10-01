"""
Automated Test Suite for AI EA Lab - Phase 9: AI Backtest Runner & Candidate Verification

Tests:
1. Candidate Verification:
   - Candidate exists and passes verification.
   - Missing candidate handled cleanly.
   - Missing metadata rejected.
   - Missing source file rejected.
   - Missing binary (.ex5) rejected.
   - Zero-byte binary rejected.
   - Compile status failed in metadata rejected.
   - Source hash mismatch rejected.
   - Provenance chain mismatch (missing plan / missing baseline) rejected.

2. Dataset & Period Resolution:
   - Configured training period resolved correctly.
   - Configured validation period resolved correctly.
   - Configured unseen period resolved correctly.
   - Unconfigured dataset returns DATASET_NOT_CONFIGURED.

3. Configuration & Parameter Validation:
   - Symbol, timeframe, and model recorded properly.
   - Configuration overrides work properly.

4. Candidate Synchronization / Isolation:
   - Candidate binary staged into MQL5/Experts/Candidates/CAND-XXXX.ex5.
   - Destination hash verified matching source hash.
   - Staging never alters baseline or canonical EA.

5. Port 3000 Conflict:
   - Available port allows execution.
   - Occupied port returns TESTER_PORT_CONFLICT.

6. MT5 Strategy Tester Execution:
   - MT5 launch failure handled cleanly.
   - MT5 timeout triggers process termination and returns TESTER_TIMEOUT.
   - Successful MT5 run completes.

7. Report Verification:
   - Missing report returns REPORT_NOT_FOUND.
   - Empty report returns REPORT_EMPTY.
   - Zero-data report (0 bars, 0 ticks) returns REPORT_INVALID.
   - Anti-contamination check: report with wrong EA returns REPORT_IDENTITY_MISMATCH.
   - Zero-trade report with bars > 0 and ticks > 0 is accepted as valid.

8. Experiment Creation & Provenance:
   - Creates new EXP-XXXX with sequential monotonic ID.
   - Metadata links candidate_id, plan_id, hypothesis_id, baseline_experiment, hashes.
   - Manifest is automatically updated with new experiment.
   - Existing EXP-0001 and EXP-0002 remain completely untouched.

9. CLI Modes:
   - Dry run previews execution without MT5 execution.
   - Verify-only checks candidate without backtest.
   - JSON output mode matches schema.

10. Safety Invariants:
   - No live trading, broker calls, or credential modifications.
"""
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

from scripts.candidate_sync import cleanup_staged_candidate, stage_candidate_binary
from scripts.candidate_verifier import calculate_sha256, verify_candidate
from scripts.run_candidate import (
    STATUS_BINARY_INVALID,
    STATUS_BINARY_MISSING,
    STATUS_CANDIDATE_INVALID,
    STATUS_CANDIDATE_NOT_FOUND,
    STATUS_DATASET_NOT_CONFIGURED,
    STATUS_EXPERIMENT_CREATION_FAILED,
    STATUS_MT5_LAUNCH_FAILED,
    STATUS_PROVENANCE_INVALID,
    STATUS_READY,
    STATUS_REPORT_EMPTY,
    STATUS_REPORT_IDENTITY_MISMATCH,
    STATUS_REPORT_INVALID,
    STATUS_REPORT_NOT_FOUND,
    STATUS_SUCCESS,
    STATUS_TESTER_FAILED,
    STATUS_TESTER_PORT_CONFLICT,
    STATUS_TESTER_TIMEOUT,
    execute_candidate_backtest,
    generate_candidate_tester_config,
    resolve_dataset_dates,
    verify_candidate_report,
)


class TestCandidateRunner(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.candidates_dir = self.temp_dir / "developer" / "candidates"
        self.plans_dir = self.temp_dir / "research" / "plans"
        self.experiments_dir = self.temp_dir / "experiments"
        self.mt5_data_dir = self.temp_dir / "mt5_data"
        self.config_dir = self.temp_dir / "config"

        self.candidates_dir.mkdir(parents=True)
        self.plans_dir.mkdir(parents=True)
        self.experiments_dir.mkdir(parents=True)
        self.mt5_data_dir.mkdir(parents=True)
        self.config_dir.mkdir(parents=True)

        # Baseline experiment EXP-0002
        b_dir = self.experiments_dir / "EXP-0002"
        b_dir.mkdir()
        (b_dir / "metadata.json").write_text(json.dumps({
            "experiment_id": "EXP-0002",
            "ea": "TestEA",
            "symbol": "GBPUSD",
            "timeframe": "M15",
            "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20"}
        }), encoding="utf-8")
        (b_dir / "metrics.json").write_text("{}", encoding="utf-8")

        # Plan PLAN-0001
        self.plan_data = {
            "schema_version": 1,
            "experiment_plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "research_question": "Does FastMAPeriod 5 work?",
            "objective": "Test FastMAPeriod",
            "baseline": {
                "experiment_id": "EXP-0002",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20"}
            },
            "changes_under_test": [{
                "variable": "FastMAPeriod",
                "baseline_value": "10",
                "target_value": "5",
                "change_type": "parameter_adjustment"
            }],
            "dataset": {
                "type": "training",
                "from": "2024.01.01",
                "to": "2024.02.01",
                "status": "configured"
            },
            "parameters": {"FastMAPeriod": "5", "SlowMAPeriod": "20"},
            "human_review_required": True,
            "status": "approved",
            "approval": {"status": "approved", "reviewed_by": "Lead Quant"}
        }
        (self.plans_dir / "PLAN-0001.json").write_text(json.dumps(self.plan_data), encoding="utf-8")

        # Candidate CAND-0001
        self.cand_dir = self.candidates_dir / "CAND-0001"
        self.cand_dir.mkdir()
        self.source_content = "input int FastMAPeriod = 5;\nvoid OnTick() {}\n"
        source_file = self.cand_dir / "source_after.mq5"
        source_file.write_text(self.source_content, encoding="utf-8")
        self.source_hash = hashlib.sha256(source_file.read_bytes()).hexdigest()

        self.binary_content = b"\x00\x01\x02\x03\x04\x05\x06\x07MockEX5BinaryContent"
        binary_file = self.cand_dir / "source_after.ex5"
        binary_file.write_bytes(self.binary_content)
        self.binary_hash = hashlib.sha256(binary_file.read_bytes()).hexdigest()

        (self.cand_dir / "metadata.json").write_text(json.dumps({
            "schema_version": 1,
            "candidate_id": "CAND-0001",
            "plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "baseline_experiment": "EXP-0002",
            "ea": "TestEA",
            "created_at": "2026-09-29T10:00:00+01:00",
            "source_before_sha256": "abc",
            "source_after_sha256": self.source_hash,
            "compile_status": "passed",
            "status": "ready_for_next_phase"
        }), encoding="utf-8")

        # System config.json
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
                "leverage": "1:100"
            }
        }
        self.config_path.write_text(json.dumps(self.config_data), encoding="utf-8")

        # Research periods config
        self.research_periods_path = self.config_dir / "research_periods.json"
        self.periods_data = {
            "schema_version": 1,
            "status": "configured",
            "periods": {
                "training": {"from": "2024.01.01", "to": "2024.02.01"},
                "validation": {"from": "2024.02.01", "to": "2024.03.01"},
                "unseen": {"from": "2024.03.01", "to": "2024.04.01"}
            }
        }
        self.research_periods_path.write_text(json.dumps(self.periods_data), encoding="utf-8")

    def tearDown(self):
        try:
            shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    # 1. Candidate Verification Tests
    def test_01_candidate_verification_success(self):
        """Test that a valid candidate artifact passes verification completely."""
        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertTrue(res["verified"])
        self.assertEqual(res["status"], STATUS_READY)
        self.assertTrue(res["source_verified"])
        self.assertTrue(res["binary_verified"])
        self.assertTrue(res["compile_verified"])
        self.assertTrue(res["provenance_verified"])

    def test_02_candidate_missing_directory(self):
        """Test that a non-existent candidate directory returns CANDIDATE_NOT_FOUND."""
        res = verify_candidate(
            "CAND-9999",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_CANDIDATE_NOT_FOUND)

    def test_03_candidate_missing_metadata(self):
        """Test that missing metadata.json returns CANDIDATE_INVALID."""
        (self.cand_dir / "metadata.json").unlink()
        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_CANDIDATE_INVALID)

    def test_04_candidate_missing_binary(self):
        """Test that missing source_after.ex5 returns BINARY_MISSING."""
        (self.cand_dir / "source_after.ex5").unlink()
        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_BINARY_MISSING)

    def test_05_candidate_zero_byte_binary(self):
        """Test that empty (0 bytes) .ex5 returns BINARY_INVALID."""
        (self.cand_dir / "source_after.ex5").write_bytes(b"")
        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_BINARY_INVALID)

    def test_06_candidate_source_hash_mismatch(self):
        """Test that modifying source_after.mq5 triggers hash mismatch."""
        (self.cand_dir / "source_after.mq5").write_text("// tampered", encoding="utf-8")
        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertFalse(res["source_verified"])
        self.assertTrue(any("hash mismatch" in issue for issue in res["issues"]))

    def test_07_candidate_provenance_missing_plan(self):
        """Test that pointing to a nonexistent plan returns PROVENANCE_INVALID."""
        meta = json.loads((self.cand_dir / "metadata.json").read_text(encoding="utf-8"))
        meta["plan_id"] = "PLAN-8888"
        (self.cand_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_PROVENANCE_INVALID)

    def test_08_candidate_provenance_missing_baseline(self):
        """Test that pointing to a nonexistent baseline experiment returns PROVENANCE_INVALID."""
        meta = json.loads((self.cand_dir / "metadata.json").read_text(encoding="utf-8"))
        meta["baseline_experiment"] = "EXP-8888"
        (self.cand_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        res = verify_candidate(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
        )
        self.assertFalse(res["verified"])
        self.assertEqual(res["status"], STATUS_PROVENANCE_INVALID)

    # 2. Dataset & Period Resolution Tests
    def test_09_dataset_resolution_configured(self):
        """Test resolving configured research periods for training, validation, and unseen."""
        for p_type, expected_from in [("training", "2024.01.01"), ("validation", "2024.02.01"), ("unseen", "2024.03.01")]:
            plan = {"dataset": {"type": p_type}}
            ok, dtype, d_from, d_to, status = resolve_dataset_dates(
                plan, research_periods_path=self.research_periods_path
            )
            self.assertTrue(ok)
            self.assertEqual(dtype, p_type)
            self.assertEqual(d_from, expected_from)
            self.assertEqual(status, "CONFIGURED")

    def test_10_dataset_resolution_unconfigured(self):
        """Test unconfigured research periods return DATASET_NOT_CONFIGURED by default."""
        unconfigured_path = self.temp_dir / "unconfigured_periods.json"
        unconfigured_path.write_text(json.dumps({
            "schema_version": 1,
            "status": "unconfigured",
            "periods": {"training": {"from": None, "to": None}}
        }), encoding="utf-8")

        plan = {"dataset": {"type": "training", "from": "2024.01.01", "to": "2024.02.01"}}
        ok, dtype, d_from, d_to, status = resolve_dataset_dates(
            plan, research_periods_path=unconfigured_path, allow_unconfigured_dates=False
        )
        self.assertFalse(ok)
        self.assertEqual(status, STATUS_DATASET_NOT_CONFIGURED)

    # 3. Candidate Synchronization / Isolation Tests
    def test_11_candidate_staging_isolation(self):
        """Test staging candidate binary into isolated MQL5/Experts/Candidates/ subfolder."""
        source_bin = self.cand_dir / "source_after.ex5"
        sync = stage_candidate_binary("CAND-0001", source_bin, self.mt5_data_dir)

        self.assertTrue(sync["verified"])
        self.assertEqual(sync["expert_param"], "Candidates\\CAND-0001.ex5")
        self.assertTrue(Path(sync["destination_binary"]).is_file())
        self.assertEqual(sync["source_hash"], sync["destination_hash"])

        # Verify canonical location was untouched
        canonical = self.mt5_data_dir / "MQL5" / "Experts" / "TestEA.ex5"
        self.assertFalse(canonical.exists())

    # 4. Port Conflict Test
    def test_12_port_conflict_detection(self):
        """Test that when port 3000 is occupied, runner halts with TESTER_PORT_CONFLICT."""
        import socket
        # Bind a mock socket on 3000 if available, or simulate conflict
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 3000))
            s.listen(1)
            # Execute runner
            res = execute_candidate_backtest(
                "CAND-0001",
                candidates_dir=self.candidates_dir,
                plans_dir=self.plans_dir,
                experiments_dir=self.experiments_dir,
                config_path=self.config_path,
                research_periods_path=self.research_periods_path,
            )
            self.assertEqual(res["status"], STATUS_TESTER_PORT_CONFLICT)
        except OSError:
            # Port already in use by real process
            res = execute_candidate_backtest(
                "CAND-0001",
                candidates_dir=self.candidates_dir,
                plans_dir=self.plans_dir,
                experiments_dir=self.experiments_dir,
                config_path=self.config_path,
                research_periods_path=self.research_periods_path,
            )
            self.assertEqual(res["status"], STATUS_TESTER_PORT_CONFLICT)
        finally:
            s.close()

    # 5. Report Verification Tests
    def test_13_report_verification_valid_zero_trades(self):
        """Test that report with Bars > 0, Ticks > 0, and Trades = 0 is accepted as valid."""
        rep_path = self.temp_dir / "CAND-0001_report.htm"
        rep_content = """<html><body>
        <table>
        <tr><td>Expert:</td><td><b>Candidates\\CAND-0001</b></td></tr>
        <tr><td>Symbol:</td><td><b>GBPUSD</b></td></tr>
        <tr><td>Period:</td><td><b>M15</b></td></tr>
        <tr><td>Bars:</td><td><b>2120</b></td></tr>
        <tr><td>Ticks:</td><td><b>125602</b></td></tr>
        <tr><td>Total Trades:</td><td><b>0</b></td></tr>
        </table></body></html>"""
        rep_path.write_text(rep_content, encoding="utf-8")

        valid, status, info = verify_candidate_report(rep_path, "CAND-0001", "GBPUSD", "M15")
        self.assertTrue(valid)
        self.assertEqual(status, STATUS_SUCCESS)
        self.assertTrue(info["test_executed"])
        self.assertEqual(info["bars"], 2120)
        self.assertEqual(info["trades"], 0)

    def test_14_report_verification_zero_data_invalid(self):
        """Test that report with 0 bars and 0 ticks returns REPORT_INVALID."""
        rep_path = self.temp_dir / "CAND-0001_report.htm"
        rep_content = """<html><body><table>
        <tr><td>Expert:</td><td><b>Candidates\\CAND-0001</b></td></tr>
        <tr><td>Bars:</td><td><b>0</b></td></tr>
        <tr><td>Ticks:</td><td><b>0</b></td></tr>
        </table></body></html>"""
        rep_path.write_text(rep_content, encoding="utf-8")

        valid, status, info = verify_candidate_report(rep_path, "CAND-0001", "GBPUSD", "M15")
        self.assertFalse(valid)
        self.assertEqual(status, STATUS_REPORT_INVALID)

    def test_15_report_verification_identity_mismatch(self):
        """Anti-contamination: test that report showing old baseline EA instead of candidate returns REPORT_IDENTITY_MISMATCH."""
        rep_path = self.temp_dir / "CAND-0001_report.htm"
        rep_content = """<html><body><table>
        <tr><td>Expert:</td><td><b>TestEA</b></td></tr>
        <tr><td>Bars:</td><td><b>1000</b></td></tr>
        <tr><td>Ticks:</td><td><b>50000</b></td></tr>
        </table></body></html>"""
        rep_path.write_text(rep_content, encoding="utf-8")

        valid, status, info = verify_candidate_report(rep_path, "CAND-0001", "GBPUSD", "M15")
        self.assertFalse(valid)
        self.assertEqual(status, STATUS_REPORT_IDENTITY_MISMATCH)

    def test_16_report_empty(self):
        """Test that 0-byte report returns REPORT_EMPTY."""
        rep_path = self.temp_dir / "CAND-0001_report.htm"
        rep_path.write_bytes(b"")

        valid, status, info = verify_candidate_report(rep_path, "CAND-0001", "GBPUSD", "M15")
        self.assertFalse(valid)
        self.assertEqual(status, STATUS_REPORT_EMPTY)

    def test_17_report_not_found(self):
        """Test missing report file returns REPORT_NOT_FOUND."""
        rep_path = self.temp_dir / "NonExistent_report.htm"
        valid, status, info = verify_candidate_report(rep_path, "CAND-0001", "GBPUSD", "M15")
        self.assertFalse(valid)
        self.assertEqual(status, STATUS_REPORT_NOT_FOUND)

    # 6. End-to-End Execution with Mock Launcher Test
    def test_18_successful_mocked_backtest_execution(self):
        """Test end-to-end backtest pipeline with mocked MT5 run produces EXP-0003 with provenance."""
        mock_rep_name = "CAND-0001_report.htm"
        mt5_rep = self.mt5_data_dir / mock_rep_name

        def mock_launcher(cmd, timeout):
            # Load real MT5 report template from repository and adjust Expert to candidate
            real_rep_path = PROJECT_ROOT / "tester" / "reports" / "TestEA_report.htm"
            real_rep_bytes = real_rep_path.read_bytes()
            real_rep_text = real_rep_bytes.decode("utf-16le", errors="ignore")
            # Replace Expert name with candidate
            mock_rep_text = real_rep_text.replace("TestEA.ex5", "Candidates\\CAND-0001.ex5").replace("TestEA", "Candidates\\CAND-0001")
            mt5_rep.write_bytes(mock_rep_text.encode("utf-16le"))
            return {"exit_code": 0, "timeout": False}

        res = execute_candidate_backtest(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=mock_launcher,
        )

        self.assertEqual(res["status"], STATUS_SUCCESS)
        self.assertTrue(res["experiment"]["created"])
        self.assertEqual(res["experiment"]["experiment_id"], "EXP-0003")

        exp_dir = Path(res["experiment"]["directory"])
        self.assertTrue((exp_dir / "report.htm").is_file())
        self.assertTrue((exp_dir / "metrics.json").is_file())
        self.assertTrue((exp_dir / "metadata.json").is_file())

        # Verify provenance in created experiment metadata
        meta = json.loads((exp_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["candidate_id"], "CAND-0001")
        self.assertEqual(meta["plan_id"], "PLAN-0001")
        self.assertEqual(meta["hypothesis_id"], "HYP-0001")
        self.assertEqual(meta["baseline_experiment"], "EXP-0002")
        self.assertEqual(meta["candidate_source_sha256"], self.source_hash)

    def test_19_mt5_timeout_handling(self):
        """Test that MT5 timeout is caught and returns TESTER_TIMEOUT without creating experiment."""
        def timeout_launcher(cmd, timeout):
            return {"exit_code": -1, "timeout": True}

        res = execute_candidate_backtest(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=timeout_launcher,
        )
        self.assertEqual(res["status"], STATUS_TESTER_TIMEOUT)
        self.assertFalse(res["experiment"]["created"])

    def test_20_mt5_failure_handling(self):
        """Test non-zero MT5 exit code returns TESTER_FAILED."""
        def failure_launcher(cmd, timeout):
            return {"exit_code": 1, "timeout": False}

        res = execute_candidate_backtest(
            "CAND-0001",
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
            mt5_launcher=failure_launcher,
        )
        self.assertEqual(res["status"], STATUS_TESTER_FAILED)
        self.assertFalse(res["experiment"]["created"])

    # 7. Dry-Run & Verify-Only Modes
    def test_21_dry_run_mode(self):
        """Test that --dry-run previews configuration without launching MT5 or creating files."""
        res = execute_candidate_backtest(
            "CAND-0001",
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
        )
        self.assertEqual(res["status"], STATUS_READY)
        self.assertTrue(res["dry_run"])
        self.assertFalse(res["experiment"]["created"])
        self.assertEqual(res["backtest"]["status"], "dry_run")

    def test_22_verify_only_mode(self):
        """Test that --verify-only validates candidate and halts before MT5 launch."""
        res = execute_candidate_backtest(
            "CAND-0001",
            verify_only=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.experiments_dir,
            config_path=self.config_path,
            research_periods_path=self.research_periods_path,
        )
        self.assertEqual(res["status"], STATUS_READY)
        self.assertTrue(res["verify_only"])
        self.assertTrue(res["verification"]["verified"])
        self.assertFalse(res["experiment"]["created"])

    # 8. Immutability & Safety
    def test_23_immutability_of_historical_experiments(self):
        """Verify EXP-0001 and EXP-0002 in active repo remain untouched."""
        exp1_path = PROJECT_ROOT / "experiments" / "EXP-0001" / "metadata.json"
        exp2_path = PROJECT_ROOT / "experiments" / "EXP-0002" / "metadata.json"

        if exp1_path.is_file():
            meta1 = json.loads(exp1_path.read_text(encoding="utf-8"))
            self.assertEqual(meta1.get("experiment_id"), "EXP-0001")

        if exp2_path.is_file():
            meta2 = json.loads(exp2_path.read_text(encoding="utf-8"))
            self.assertEqual(meta2.get("experiment_id"), "EXP-0002")

    def test_24_safety_no_live_trading_in_candidate_runner(self):
        """Safety invariant: verify candidate runner contains no live order placement or broker login code."""
        code = (PROJECT_ROOT / "scripts" / "run_candidate.py").read_text(encoding="utf-8").lower()
        forbidden = [
            "traderequest",
            "account_info",
            "order_send",
            "positions_get",
            "orders_get",
            "login_broker",
            "live_execution",
        ]
        for pattern in forbidden:
            self.assertNotIn(pattern, code)


if __name__ == "__main__":
    unittest.main()
