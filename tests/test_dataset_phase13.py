"""
Phase 13 Test Suite: Dataset-Aware Experiments and Enforcement.

Verifies:
A. Valid training dataset resolution
B. Valid validation dataset resolution
C. Valid unseen dataset resolution
D. Missing dataset in an experiment plan
E. Invalid dataset name
F. Plan dataset -> execution period consistency
G. Dataset mismatch detection
H. Unseen is never selected automatically
I. Experiment records resolved dataset metadata
J. Auditor detects dataset mismatch
K. Historical experiments remain unchanged
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.candidate_verifier import calculate_sha256
from scripts.auditor import audit_dataset
from scripts.research_periods import resolve_dataset_partition
from scripts.run_candidate import (
    STATUS_DATASET_MISMATCH,
    STATUS_DATASET_MISSING,
    STATUS_INVALID_DATASET,
    execute_candidate_backtest,
    resolve_dataset_dates,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"


class TestDatasetPhase13(unittest.TestCase):
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

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_A_valid_training_dataset_resolution(self):
        """A. Valid training dataset resolution returns exact configured dates."""
        success, norm_p, p_from, p_to, st = resolve_dataset_partition("training", config_path=self.cfg_path)
        self.assertTrue(success)
        self.assertEqual(norm_p, "training")
        self.assertEqual(p_from, "2020.01.01")
        self.assertEqual(p_to, "2024.12.31")

        plan = {"dataset": "training"}
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertTrue(ok)
        self.assertEqual(dtype, "training")
        self.assertEqual(d_from, "2020.01.01")
        self.assertEqual(d_to, "2024.12.31")

    def test_B_valid_validation_dataset_resolution(self):
        """B. Valid validation dataset resolution returns exact configured dates."""
        success, norm_p, p_from, p_to, st = resolve_dataset_partition("validation", config_path=self.cfg_path)
        self.assertTrue(success)
        self.assertEqual(norm_p, "validation")
        self.assertEqual(p_from, "2025.01.01")
        self.assertEqual(p_to, "2025.12.31")

        plan = {"dataset": "validation"}
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertTrue(ok)
        self.assertEqual(dtype, "validation")
        self.assertEqual(d_from, "2025.01.01")
        self.assertEqual(d_to, "2025.12.31")

    def test_C_valid_unseen_dataset_resolution(self):
        """C. Valid unseen dataset resolution returns exact configured dates."""
        success, norm_p, p_from, p_to, st = resolve_dataset_partition("unseen", config_path=self.cfg_path)
        self.assertTrue(success)
        self.assertEqual(norm_p, "unseen")
        self.assertEqual(p_from, "2026.01.01")
        self.assertEqual(p_to, "2026.09.30")

        plan = {"dataset": "unseen"}
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertTrue(ok)
        self.assertEqual(dtype, "unseen")
        self.assertEqual(d_from, "2026.01.01")
        self.assertEqual(d_to, "2026.09.30")

    def test_D_missing_dataset_in_plan(self):
        """D. Missing dataset in plan returns DATASET_MISSING status."""
        plan = {}
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertFalse(ok)
        self.assertEqual(st_code, STATUS_DATASET_MISSING)

    def test_E_invalid_dataset_name(self):
        """E. Invalid dataset partition name returns INVALID_DATASET status."""
        plan = {"dataset": "non_existent_partition"}
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertFalse(ok)
        self.assertEqual(st_code, STATUS_INVALID_DATASET)

    def test_F_plan_dataset_execution_period_consistency(self):
        """F. Plan dataset matching partition resolves exact period consistency."""
        plan = {
            "dataset": {
                "partition": "training",
                "from": "2020.01.01",
                "to": "2024.12.31",
            }
        }
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertTrue(ok)
        self.assertEqual(d_from, "2020.01.01")
        self.assertEqual(d_to, "2024.12.31")

    def test_G_dataset_mismatch_detection(self):
        """G. Plan specifying dates that mismatch configured partition returns DATASET_MISMATCH."""
        plan = {
            "dataset": {
                "partition": "validation",
                "from": "2024.01.01",
                "to": "2024.02.01",  # Validation is 2025.01.01 - 2025.12.31
            }
        }
        ok, dtype, d_from, d_to, st_code = resolve_dataset_dates(plan, research_periods_path=self.cfg_path)
        self.assertFalse(ok)
        self.assertEqual(st_code, STATUS_DATASET_MISMATCH)

    def test_H_unseen_never_selected_automatically(self):
        """H. UNSEEN dataset partition is never selected unless explicitly requested."""
        plan_training = {"dataset": "training"}
        ok1, dtype1, _, _, _ = resolve_dataset_dates(plan_training, research_periods_path=self.cfg_path)
        self.assertEqual(dtype1, "training")

        plan_missing = {}
        ok2, dtype2, _, _, _ = resolve_dataset_dates(plan_missing, research_periods_path=self.cfg_path)
        self.assertNotEqual(dtype2, "unseen")

    def test_I_experiment_records_resolved_dataset_metadata(self):
        """I. Candidate execution records structured dataset metadata in experiment."""
        exps_dir = self.temp_dir / "experiments"
        exps_dir.mkdir(parents=True)
        exp1_dir = exps_dir / "EXP-0001"
        exp1_dir.mkdir(parents=True)
        (exp1_dir / "metadata.json").write_text(json.dumps({"experiment_id": "EXP-0001"}), encoding="utf-8")

        cand_dir = self.temp_dir / "candidates" / "CAND-0001"
        cand_dir.mkdir(parents=True)
        src_path = cand_dir / "source_after.mq5"
        bin_path = cand_dir / "source_after.ex5"
        src_path.write_text("// MQ5 source", encoding="utf-8")
        bin_path.write_text("EX5 binary", encoding="utf-8")
        meta = {
            "candidate_id": "CAND-0001",
            "plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "baseline_experiment": "EXP-0001",
            "ea": "TestEA",
            "compile_status": "passed",
            "authorized_changes": [],
            "unauthorized_changes": [],
            "source_after_sha256": calculate_sha256(src_path),
            "source_after_ex5_sha256": calculate_sha256(bin_path),
        }
        (cand_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")

        plans_dir = self.temp_dir / "plans"
        plans_dir.mkdir(parents=True)
        plan = {
            "experiment_plan_id": "PLAN-0001",
            "hypothesis_id": "HYP-0001",
            "dataset": {"partition": "training", "from": "2020.01.01", "to": "2024.12.31"},
            "baseline": {"experiment_id": "EXP-0001", "symbol": "GBPUSD", "timeframe": "M15"},
        }
        (plans_dir / "PLAN-0001.json").write_text(json.dumps(plan), encoding="utf-8")

        res = execute_candidate_backtest(
            candidate_id="CAND-0001",
            dry_run=True,
            candidates_dir=self.temp_dir / "candidates",
            plans_dir=plans_dir,
            experiments_dir=exps_dir,
            config_path=PROJECT_ROOT / "config.json",
            research_periods_path=self.cfg_path,
        )
        self.assertEqual(res["status"], "READY")
        self.assertEqual(res["backtest"]["configuration"]["dataset"], "training")
        self.assertEqual(res["backtest"]["configuration"]["from"], "2020.01.01")
        self.assertEqual(res["backtest"]["configuration"]["to"], "2024.12.31")

    def test_J_auditor_detects_dataset_mismatch(self):
        """J. Auditor detects missing dataset, plan mismatch, or date mismatch."""
        exp_meta_mismatch = {
            "from": "2020.01.01",
            "to": "2024.12.31",
            "dataset": {
                "partition": "training",
                "from": "2020.01.01",
                "to": "2024.12.31",
            },
        }
        plan_validation = {"dataset": "validation"}  # Plan expects validation, exp has training
        res = audit_dataset(exp_meta_mismatch, self.cfg_path, plan_data=plan_validation)
        self.assertEqual(res["status"], "FAIL")
        self.assertIn("Plan dataset partition", res["details"])

        exp_meta_date_mismatch = {
            "from": "2024.01.01",  # Configured training is 2020.01.01
            "to": "2024.12.31",
            "dataset": {
                "partition": "training",
                "from": "2024.01.01",
                "to": "2024.12.31",
            },
        }
        plan_training = {"dataset": "training"}
        res2 = audit_dataset(exp_meta_date_mismatch, self.cfg_path, plan_data=plan_training)
        self.assertEqual(res2["status"], "FAIL")
        self.assertIn("does not match configured period", res2["details"])

    def test_K_historical_experiments_remain_unchanged(self):
        """K. Historical experiments EXP-0001, EXP-0002, EXP-0004, EXP-0005 are intact."""
        for exp_id in ["EXP-0001", "EXP-0002", "EXP-0004", "EXP-0005"]:
            exp_meta_file = EXPERIMENTS_DIR / exp_id / "metadata.json"
            if exp_meta_file.exists():
                meta = json.loads(exp_meta_file.read_text(encoding="utf-8"))
                self.assertEqual(meta.get("experiment_id"), exp_id)
                res = audit_dataset(meta, RESEARCH_PERIODS_PATH)
                self.assertIn(res["status"], ["CONFIGURED", "UNCONFIGURED"])


if __name__ == "__main__":
    unittest.main()
