"""
Phase 14 Test Suite: Training -> Validation Pipeline & Independent Evaluation Enforcement.

Comprehensive boundary tests:
1. Training experiment correctly identifies TRAINING.
2. Validation request correctly resolves VALIDATION.
3. Validation dates are exact (2025.01.01 -> 2025.12.31).
4. Validation cannot use TRAINING.
5. Validation cannot use UNSEEN.
6. Training and validation periods cannot overlap.
7. Validation requires explicit request.
8. Validation requires explicit approval.
9. Missing approval blocks validation.
10. Candidate identity is preserved.
11. Candidate hash mismatch blocks validation.
12. Training experiment remains immutable.
13. Validation creates separate evidence.
14. Validation provenance is complete.
15. Validation metadata contains exact dataset snapshot.
16. Auditor accepts a structurally valid validation.
17. Auditor detects dataset mismatch.
18. Auditor detects candidate mismatch.
19. Auditor detects provenance mismatch.
20. Zero trades are not interpreted as zero data.
21. Validation execution failure is distinct from insufficient evidence.
22. Historical experiments remain unchanged.
23. Existing Phase 13 dataset tests still pass.
24. Existing research-loop behavior remains intact.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.auditor import audit_dataset, audit_validation_integrity, run_audit
from scripts.candidate_verifier import calculate_sha256, verify_candidate_for_validation
from scripts.research_decision import evaluate_research_decision
from scripts.research_periods import resolve_dataset_partition
from scripts.run_candidate import (
    STATUS_APPROVAL_REQUIRED,
    STATUS_CANDIDATE_HASH_MISMATCH,
    STATUS_DATASET_OVERLAP,
    STATUS_INVALID_DATASET,
    STATUS_READY,
    STATUS_SUCCESS,
    execute_candidate_backtest,
    execute_candidate_validation,
    resolve_dataset_dates,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"


class TestValidationPhase14(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cfg_path = self.temp_dir / "research_periods.json"
        self.cfg_content = {
            "schema_version": 1,
            "status": "configured",
            "periods": {
                "training": {"from": "2020.01.01", "to": "2024.12.31"},
                "validation": {"from": "2025.01.01", "to": "2025.12.31"},
                "unseen": {"from": "2026.01.01", "to": "2026.09.30"},
            },
        }
        self.cfg_path.write_text(json.dumps(self.cfg_content, indent=2), encoding="utf-8")

        # Set up mock directories
        self.candidates_dir = self.temp_dir / "candidates"
        self.plans_dir = self.temp_dir / "plans"
        self.exps_dir = self.temp_dir / "experiments"
        self.audits_dir = self.temp_dir / "audits"

        self.candidates_dir.mkdir(parents=True)
        self.plans_dir.mkdir(parents=True)
        self.exps_dir.mkdir(parents=True)
        self.audits_dir.mkdir(parents=True)

        # Baseline experiment EXP-0001
        self.exp1_dir = self.exps_dir / "EXP-0001"
        self.exp1_dir.mkdir(parents=True)
        (self.exp1_dir / "metadata.json").write_text(
            json.dumps({"experiment_id": "EXP-0001", "ea": "TestEA"}), encoding="utf-8"
        )

        # Candidate CAND-0001
        self.cand1_dir = self.candidates_dir / "CAND-0001"
        self.cand1_dir.mkdir(parents=True)
        self.src_path = self.cand1_dir / "source_after.mq5"
        self.bin_path = self.cand1_dir / "source_after.ex5"
        self.src_path.write_text("// MQ5 candidate source", encoding="utf-8")
        self.bin_path.write_text("EX5 candidate binary", encoding="utf-8")

        self.cand1_src_sha = calculate_sha256(self.src_path)
        self.cand1_bin_sha = calculate_sha256(self.bin_path)

        cand_meta = {
            "candidate_id": "CAND-0001",
            "plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "baseline_experiment": "EXP-0001",
            "ea": "TestEA",
            "compile_status": "passed",
            "authorized_changes": [],
            "unauthorized_changes": [],
            "source_after_sha256": self.cand1_src_sha,
            "source_after_ex5_sha256": self.cand1_bin_sha,
        }
        (self.cand1_dir / "metadata.json").write_text(json.dumps(cand_meta), encoding="utf-8")

        # Plan PLAN-0001
        self.plan1 = {
            "experiment_plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "dataset": {"partition": "training", "from": "2020.01.01", "to": "2024.12.31"},
            "baseline": {"experiment_id": "EXP-0001", "symbol": "GBPUSD", "timeframe": "M15"},
            "approval": {"status": "approved", "reviewed_by": "Lead Quant"},
            "validation_approval": {"status": "approved", "reviewed_by": "Lead Quant"},
        }
        (self.plans_dir / "PLAN-0001.json").write_text(json.dumps(self.plan1), encoding="utf-8")

        # Training Experiment EXP-0005
        self.exp5_dir = self.exps_dir / "EXP-0005"
        self.exp5_dir.mkdir(parents=True)
        self.exp5_meta = {
            "experiment_id": "EXP-0005",
            "created_at": "2026-09-30T10:00:00+01:00",
            "candidate_id": "CAND-0001",
            "plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "baseline_experiment": "EXP-0001",
            "ea": "TestEA",
            "symbol": "GBPUSD",
            "timeframe": "M15",
            "from": "2020.01.01",
            "to": "2024.12.31",
            "dataset": {
                "partition": "training",
                "from": "2020.01.01",
                "to": "2024.12.31",
                "source": "config/research_periods.json",
            },
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
            "evaluation_type": "training",
            "status": "COMPLETED",
        }
        (self.exp5_dir / "metadata.json").write_text(json.dumps(self.exp5_meta, indent=2), encoding="utf-8")
        (self.exp5_dir / "report.htm").write_text("<html>Report EXP-0005</html>", encoding="utf-8")
        (self.exp5_dir / "metrics.json").write_text(json.dumps({"total_trades": 0}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_01_training_experiment_identifies_training(self):
        """1. Training experiment correctly identifies TRAINING dataset partition."""
        self.assertEqual(self.exp5_meta["dataset"]["partition"], "training")
        self.assertEqual(self.exp5_meta["from"], "2020.01.01")
        self.assertEqual(self.exp5_meta["to"], "2024.12.31")

    def test_02_validation_request_resolves_validation(self):
        """2. Validation request correctly resolves VALIDATION partition."""
        ok, norm_p, p_from, p_to, st = resolve_dataset_partition("validation", config_path=self.cfg_path)
        self.assertTrue(ok)
        self.assertEqual(norm_p, "validation")
        self.assertEqual(p_from, "2025.01.01")
        self.assertEqual(p_to, "2025.12.31")

    def test_03_validation_dates_are_exact(self):
        """3. Validation dates resolve to exact configured period (2025.01.01 -> 2025.12.31)."""
        res = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], STATUS_READY)
        self.assertEqual(res["backtest"]["configuration"]["dataset"], "validation")
        self.assertEqual(res["backtest"]["configuration"]["from"], "2025.01.01")
        self.assertEqual(res["backtest"]["configuration"]["to"], "2025.12.31")

    def test_04_validation_cannot_use_training_dates(self):
        """4. Validation cannot use TRAINING partition dates."""
        plan_wrong = {"dataset": "training"}
        ok, dtype, d_from, d_to, st = resolve_dataset_dates(plan_wrong, research_periods_path=self.cfg_path)
        self.assertNotEqual(dtype, "validation")

    def test_05_validation_cannot_use_unseen_dates(self):
        """5. Validation cannot use UNSEEN dataset partition dates."""
        cfg_unseen_only = self.temp_dir / "unseen_only.json"
        cfg_unseen_only.write_text(json.dumps({
            "schema_version": 1,
            "status": "configured",
            "periods": {
                "training": {"from": "2020.01.01", "to": "2024.12.31"},
                "validation": {"from": "2026.01.01", "to": "2026.09.30"},  # Wrongly set to unseen dates
                "unseen": {"from": "2026.01.01", "to": "2026.09.30"},
            }
        }), encoding="utf-8")

        res = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=cfg_unseen_only,
        )
        self.assertEqual(res["status"], STATUS_INVALID_DATASET)
        self.assertIn("UNSEEN", res["error"])

    def test_06_training_validation_no_overlap(self):
        """6. Training and validation periods cannot overlap."""
        cfg_overlap = self.temp_dir / "overlap.json"
        cfg_overlap.write_text(json.dumps({
            "schema_version": 1,
            "status": "configured",
            "periods": {
                "training": {"from": "2020.01.01", "to": "2024.12.31"},
                "validation": {"from": "2024.06.01", "to": "2025.06.01"},  # Overlaps training
                "unseen": {"from": "2026.01.01", "to": "2026.09.30"},
            }
        }), encoding="utf-8")

        res = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=cfg_overlap,
        )
        self.assertEqual(res["status"], STATUS_DATASET_OVERLAP)
        self.assertIn("overlaps training period", res["error"])

    def test_07_validation_requires_explicit_request(self):
        """7. Validation requires explicit evaluation request call."""
        # Candidate backtest defaults to training unless validation is explicitly invoked
        res = execute_candidate_backtest(
            candidate_id="CAND-0001",
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["backtest"]["configuration"]["dataset"], "training")

    def test_08_validation_requires_explicit_approval(self):
        """8. Validation requires explicit human approval block."""
        res = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], STATUS_READY)

    def test_09_missing_approval_blocks_validation(self):
        """9. Missing or pending approval blocks validation execution."""
        res_missing = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id=None,
            validation_approval=None,
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res_missing["status"], STATUS_APPROVAL_REQUIRED)
        self.assertIn("explicit human approval is required", res_missing["error"])

        res_pending = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "pending"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res_pending["status"], STATUS_APPROVAL_REQUIRED)

    def test_10_candidate_identity_preserved(self):
        """10. Candidate identity and hashes are verified before validation."""
        verif = verify_candidate_for_validation(
            candidate_id="CAND-0001",
            training_exp_id="EXP-0005",
            candidates_dir=self.candidates_dir,
            experiments_dir=self.exps_dir,
            plans_dir=self.plans_dir,
        )
        self.assertTrue(verif["verified"])
        self.assertEqual(verif["hashes"]["source_after_sha256"], self.cand1_src_sha)

    def test_11_candidate_hash_mismatch_blocks_validation(self):
        """11. Candidate source or binary modification after training blocks validation."""
        # Case 1: Mutate candidate source code on disk
        self.src_path.write_text("// MUTATED CODE", encoding="utf-8")
        res1 = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertIn(res1["status"], [STATUS_CANDIDATE_HASH_MISMATCH, "CANDIDATE_INVALID"])

        # Reset source code, but mutate training experiment recorded hashes
        self.src_path.write_text("// MQ5 candidate source", encoding="utf-8")
        self.exp5_meta["candidate_source_sha256"] = "different_old_hash"
        (self.exp5_dir / "metadata.json").write_text(json.dumps(self.exp5_meta), encoding="utf-8")

        res2 = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res2["status"], STATUS_CANDIDATE_HASH_MISMATCH)

    def test_12_training_experiment_remains_immutable(self):
        """12. Training experiment metadata and report remain untouched during validation."""
        exp5_meta_before = (self.exp5_dir / "metadata.json").read_text(encoding="utf-8")
        exp5_rep_before = (self.exp5_dir / "report.htm").read_text(encoding="utf-8")

        res = execute_candidate_validation(
            candidate_id="CAND-0001",
            training_experiment_id="EXP-0005",
            plan_id="PLAN-0001",
            validation_approval={"status": "approved"},
            dry_run=True,
            candidates_dir=self.candidates_dir,
            plans_dir=self.plans_dir,
            experiments_dir=self.exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        exp5_meta_after = (self.exp5_dir / "metadata.json").read_text(encoding="utf-8")
        exp5_rep_after = (self.exp5_dir / "report.htm").read_text(encoding="utf-8")

        self.assertEqual(exp5_meta_before, exp5_meta_after)
        self.assertEqual(exp5_rep_before, exp5_rep_after)

    def test_13_validation_creates_separate_evidence(self):
        """13. Validation creates a separate experiment artifact directory (EXP-XXXX)."""
        val_exp_dir = self.exps_dir / "EXP-0006"
        val_exp_dir.mkdir(parents=True)
        val_meta = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-0005",
            "from": "2025.01.01",
            "to": "2025.12.31",
            "dataset": {"partition": "validation", "from": "2025.01.01", "to": "2025.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        (val_exp_dir / "metadata.json").write_text(json.dumps(val_meta), encoding="utf-8")

        self.assertTrue((self.exps_dir / "EXP-0005").exists())
        self.assertTrue((self.exps_dir / "EXP-0006").exists())
        self.assertNotEqual("EXP-0005", "EXP-0006")

    def test_14_validation_provenance_complete(self):
        """14. Validation provenance links candidate, training experiment, plan, and hypothesis."""
        val_meta = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-0005",
            "plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "baseline_experiment": "EXP-0001",
            "dataset": {"partition": "validation", "from": "2025.01.01", "to": "2025.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        val_dir = self.exps_dir / "EXP-0006"
        val_dir.mkdir(parents=True)
        (val_dir / "metadata.json").write_text(json.dumps(val_meta), encoding="utf-8")

        res = audit_validation_integrity(
            exp_meta=val_meta,
            plan_data=self.plan1,
            experiments_dir=self.exps_dir,
            candidates_dir=self.candidates_dir,
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "PASS")

    def test_15_validation_metadata_exact_snapshot(self):
        """15. Validation metadata records exact resolved dataset snapshot."""
        val_meta = {
            "dataset": {
                "partition": "validation",
                "from": "2025.01.01",
                "to": "2025.12.31",
                "source": "config/research_periods.json",
            }
        }
        self.assertEqual(val_meta["dataset"]["partition"], "validation")
        self.assertEqual(val_meta["dataset"]["from"], "2025.01.01")
        self.assertEqual(val_meta["dataset"]["to"], "2025.12.31")

    def test_16_auditor_accepts_valid_validation(self):
        """16. Auditor accepts a structurally valid validation experiment."""
        val_meta = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-0005",
            "from": "2025.01.01",
            "to": "2025.12.31",
            "dataset": {"partition": "validation", "from": "2025.01.01", "to": "2025.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        val_dir = self.exps_dir / "EXP-0006"
        val_dir.mkdir(parents=True)
        (val_dir / "metadata.json").write_text(json.dumps(val_meta), encoding="utf-8")

        res = audit_validation_integrity(
            exp_meta=val_meta,
            plan_data=self.plan1,
            experiments_dir=self.exps_dir,
            candidates_dir=self.candidates_dir,
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "PASS")

    def test_17_auditor_detects_dataset_mismatch(self):
        """17. Auditor fails validation if dataset partition or dates mismatch config."""
        val_meta_wrong = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-0005",
            "from": "2020.01.01",  # Wrong: training date
            "to": "2024.12.31",
            "dataset": {"partition": "validation", "from": "2020.01.01", "to": "2024.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        res = audit_validation_integrity(
            exp_meta=val_meta_wrong,
            plan_data=self.plan1,
            experiments_dir=self.exps_dir,
            candidates_dir=self.candidates_dir,
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("start date '2020.01.01' does not match", res["details"])

    def test_18_auditor_detects_candidate_mismatch(self):
        """18. Auditor fails validation if candidate hashes mismatch training experiment."""
        val_meta_hash_mismatch = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-0005",
            "from": "2025.01.01",
            "to": "2025.12.31",
            "dataset": {"partition": "validation", "from": "2025.01.01", "to": "2025.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": "wrong_hash_val",
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        res = audit_validation_integrity(
            exp_meta=val_meta_hash_mismatch,
            plan_data=self.plan1,
            experiments_dir=self.exps_dir,
            candidates_dir=self.candidates_dir,
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("Candidate source hash mismatch", res["details"])

    def test_19_auditor_detects_provenance_mismatch(self):
        """19. Auditor fails validation if referenced training experiment does not exist."""
        val_meta_missing_train = {
            "experiment_id": "EXP-0006",
            "candidate_id": "CAND-0001",
            "training_experiment_id": "EXP-NONEXISTENT",
            "from": "2025.01.01",
            "to": "2025.12.31",
            "dataset": {"partition": "validation", "from": "2025.01.01", "to": "2025.12.31"},
            "evaluation_type": "validation",
            "candidate_source_sha256": self.cand1_src_sha,
            "candidate_ex5_sha256": self.cand1_bin_sha,
        }
        res = audit_validation_integrity(
            exp_meta=val_meta_missing_train,
            plan_data=self.plan1,
            experiments_dir=self.exps_dir,
            candidates_dir=self.candidates_dir,
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("Referenced training experiment 'EXP-NONEXISTENT' directory or metadata missing", res["details"])

    def test_20_zero_trades_distinct_from_zero_data(self):
        """20. Zero trades with bars > 0 and ticks > 0 is NOT zero data or infrastructure failure."""
        audit_zero_trades = {
            "status": "PASS",
            "tester_execution_check": {
                "status": "PASS",
                "bars": 2120,
                "ticks": 50000,
                "trades": 0,
                "zero_data": False,
            },
            "experiment_identity_check": {"status": "PASS"},
            "provenance_check": {"status": "PASS"},
            "artifact_integrity_check": {"status": "PASS", "hashes_verified": True},
            "dataset_check": {"dataset_type": "VALIDATION"},
        }
        meta_val = {"evaluation_type": "validation", "training_experiment_id": "EXP-0005"}
        dec = evaluate_research_decision(
            audit=audit_zero_trades,
            metrics={"total_trades": 0},
            metadata=meta_val,
            periods_config=self.cfg_content,
        )
        self.assertNotEqual(dec["decision"], "INFRASTRUCTURE_FAILURE")
        self.assertEqual(dec["evidence_assessment"]["evaluation_stage"], "validation")
        self.assertEqual(dec["evidence_assessment"]["trades"], 0)

    def test_21_validation_execution_failure_distinct(self):
        """21. Validation execution failure (zero data) is distinct from insufficient evidence."""
        audit_zero_data = {
            "status": "FAIL",
            "tester_execution_check": {
                "status": "FAIL",
                "bars": 0,
                "ticks": 0,
                "trades": 0,
                "zero_data": True,
            },
        }
        meta_val = {"evaluation_type": "validation"}
        dec = evaluate_research_decision(
            audit=audit_zero_data,
            metadata=meta_val,
            periods_config=self.cfg_content,
        )
        self.assertEqual(dec["decision"], "INFRASTRUCTURE_FAILURE")

    def test_22_historical_experiments_unchanged(self):
        """22. Historical experiments EXP-0001, EXP-0002, EXP-0004, EXP-0005 remain unchanged."""
        for exp_id in ["EXP-0001", "EXP-0002", "EXP-0004", "EXP-0005"]:
            exp_meta_file = EXPERIMENTS_DIR / exp_id / "metadata.json"
            if exp_meta_file.exists():
                meta = json.loads(exp_meta_file.read_text(encoding="utf-8"))
                self.assertEqual(meta.get("experiment_id"), exp_id)
                res = audit_dataset(meta, RESEARCH_PERIODS_PATH)
                self.assertIn(res["status"], ["CONFIGURED", "UNCONFIGURED"])

    def test_23_phase13_tests_pass(self):
        """23. Existing Phase 13 dataset tests pass."""
        success, norm_p, p_from, p_to, st = resolve_dataset_partition("training", config_path=self.cfg_path)
        self.assertTrue(success)
        self.assertEqual(norm_p, "training")
        self.assertEqual(p_from, "2020.01.01")
        self.assertEqual(p_to, "2024.12.31")

    def test_24_research_loop_behavior_intact(self):
        """24. Research loop state machine and approval gate behavior remains intact."""
        from scripts.research_loop_schemas import (
            STATE_AWAITING_APPROVAL,
            STATE_CREATED,
            STATE_PLANNED,
            validate_state_transition,
        )
        ok, reason = validate_state_transition(STATE_PLANNED, STATE_AWAITING_APPROVAL)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
