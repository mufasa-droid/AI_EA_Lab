"""
Automated Test Suite for AI EA Lab - Experiment Intelligence Layer

Tests:
1. Manifest generation and schema conformance
2. Deterministic manifest regeneration
3. Preservation of existing EXP-0001
4. Preservation of existing EXP-0002
5. CLI experiment comparison (EXP-0001 vs EXP-0002)
6. Machine-readable JSON comparison output validity
7. Missing metric handling in comparison
8. Non-existent experiment handling with clean error
9. Invalid experiment directory handling during manifest build
10. Research-period classification (training, validation, unseen)
11. Ambiguous and out-of-bounds period handling
12. Validation data integrity rules
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_manifest import build_manifest, extract_manifest_entry
from scripts.compare_experiments import (
    compare_experiments,
    extract_comparison_data,
    load_experiment,
    safe_diff,
)
from scripts.research_periods import (
    classify_experiment_period,
    is_periods_configured,
    load_research_periods,
    parse_date,
    validate_research_periods_integrity,
)
from scripts.validation import validate_experiment_dir


class TestExperimentIntelligence(unittest.TestCase):

    def setUp(self):
        self.experiments_dir = PROJECT_ROOT / "experiments"
        self.exp1_dir = self.experiments_dir / "EXP-0001"
        self.exp2_dir = self.experiments_dir / "EXP-0002"

    def test_01_manifest_generation(self):
        """Test manifest generation on active repository."""
        manifest = build_manifest(quiet=True)
        self.assertIsInstance(manifest, dict)
        self.assertEqual(manifest.get("schema_version"), 1)
        self.assertIn("generated_at", manifest)
        self.assertGreaterEqual(manifest.get("total_experiments", 0), 2)

        exp_ids = [e["id"] for e in manifest["experiments"]]
        self.assertIn("EXP-0001", exp_ids)
        self.assertIn("EXP-0002", exp_ids)

        # Check required fields on EXP-0001 entry
        exp1_entry = next(e for e in manifest["experiments"] if e["id"] == "EXP-0001")
        required_keys = [
            "id", "created_at", "ea", "symbol", "timeframe",
            "from", "to", "net_profit", "profit_factor",
            "total_trades", "max_drawdown", "experiment_path",
            "dataset", "dataset_status", "validation_passed"
        ]
        for key in required_keys:
            self.assertIn(key, exp1_entry, f"Missing key in manifest: {key}")

        self.assertEqual(exp1_entry["ea"], "TestEA")
        self.assertEqual(exp1_entry["symbol"], "GBPUSD")
        self.assertEqual(exp1_entry["timeframe"], "M15")
        self.assertTrue(exp1_entry["validation_passed"])

    def test_02_manifest_regeneration_deterministic(self):
        """Test that regenerating the manifest is deterministic and preserves IDs."""
        manifest1 = build_manifest(quiet=True)
        manifest2 = build_manifest(quiet=True)

        self.assertEqual(manifest1["total_experiments"], manifest2["total_experiments"])
        exps1 = manifest1["experiments"]
        exps2 = manifest2["experiments"]
        self.assertEqual(len(exps1), len(exps2))

        for e1, e2 in zip(exps1, exps2):
            self.assertEqual(e1["id"], e2["id"])
            self.assertEqual(e1["ea"], e2["ea"])
            self.assertEqual(e1["net_profit"], e2["net_profit"])
            self.assertEqual(e1["total_trades"], e2["total_trades"])

    def test_03_exp0001_preserved(self):
        """Verify EXP-0001 files and contents are completely intact."""
        self.assertTrue(self.exp1_dir.exists())
        self.assertTrue((self.exp1_dir / "metadata.json").exists())
        self.assertTrue((self.exp1_dir / "metrics.json").exists())
        self.assertTrue((self.exp1_dir / "report.htm").exists())
        self.assertTrue((self.exp1_dir / "charts").is_dir())

        meta = json.loads((self.exp1_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta.get("experiment_id"), "EXP-0001")
        self.assertEqual(meta.get("ea"), "TestEA")
        self.assertEqual(meta.get("symbol"), "GBPUSD")

        metrics = json.loads((self.exp1_dir / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(metrics["settings"]["expert"], "TestEA")
        self.assertEqual(metrics["metrics"]["total_trades"], 0)

    def test_04_exp0002_preserved(self):
        """Verify EXP-0002 files and contents are completely intact."""
        self.assertTrue(self.exp2_dir.exists())
        self.assertTrue((self.exp2_dir / "metadata.json").exists())
        self.assertTrue((self.exp2_dir / "metrics.json").exists())
        self.assertTrue((self.exp2_dir / "report.htm").exists())

        meta = json.loads((self.exp2_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta.get("experiment_id"), "EXP-0002")
        self.assertEqual(meta.get("note"), "Verification of EXP-0002 preservation")

    def test_05_compare_cli_two_experiments(self):
        """Test comparing EXP-0001 and EXP-0002 via CLI and check for factual output."""
        res = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "compare_experiments.py"), "EXP-0001", "EXP-0002"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        output = res.stdout

        # Verify sections are present
        self.assertIn("--- SETTINGS ---", output)
        self.assertIn("--- DATA QUALITY ---", output)
        self.assertIn("--- PERFORMANCE ---", output)
        self.assertIn("--- RISK ---", output)
        self.assertIn("--- TRADING ---", output)

        # Verify factual values
        self.assertIn("Total Net Profit", output)
        self.assertIn("Profit Factor", output)
        self.assertIn("Bars", output)
        self.assertIn("Ticks", output)

        # Ensure NO ranking / winner labels
        for forbidden in ["Winner", "Best", "Superior", "Optimal", "Recommended", "Rank"]:
            self.assertNotIn(forbidden, output)

    def test_06_json_comparison_output_valid(self):
        """Test comparison JSON output schema and metrics."""
        res = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "compare_experiments.py"), "EXP-0001", "EXP-0002", "--json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)

        self.assertEqual(data.get("schema_version"), 1)
        self.assertEqual(data.get("experiments"), ["EXP-0001", "EXP-0002"])

        comparisons = data.get("comparisons", {})
        self.assertIn("total_net_profit", comparisons)
        self.assertIn("profit_factor", comparisons)
        self.assertIn("bars", comparisons)
        self.assertIn("ticks", comparisons)
        self.assertIn("total_trades", comparisons)

        # Check structure of a numeric comparison
        np_comp = comparisons["total_net_profit"]
        self.assertEqual(np_comp["EXP-0001"], 0.0)
        self.assertEqual(np_comp["EXP-0002"], 0.0)
        self.assertEqual(np_comp["change"], 0.0)

    def test_07_missing_metric_handling(self):
        """Test that comparison handles missing metrics and None fields gracefully without raising exceptions."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Create EXP-0010 with partial/null metrics
            e1 = tmp_path / "EXP-0010"
            e1.mkdir()
            (e1 / "report.htm").write_text("<html>Report</html>", encoding="utf-8")
            (e1 / "metadata.json").write_text(json.dumps({
                "experiment_id": "EXP-0010",
                "ea": "SparseEA",
            }), encoding="utf-8")
            (e1 / "metrics.json").write_text(json.dumps({
                "schema_version": 1,
                "settings": {"expert": "SparseEA"},
                "metrics": {
                    "total_net_profit": None,
                    "profit_factor": None,
                    "bars": 500,
                    # Ticks intentionally omitted
                }
            }), encoding="utf-8")

            # Create EXP-0011
            e2 = tmp_path / "EXP-0011"
            e2.mkdir()
            (e2 / "report.htm").write_text("<html>Report</html>", encoding="utf-8")
            (e2 / "metrics.json").write_text(json.dumps({
                "schema_version": 1,
                "settings": {"expert": "SparseEA"},
                "metrics": {
                    "total_net_profit": 150.0,
                    "profit_factor": 1.5,
                    "bars": 600,
                    "ticks": 1000,
                }
            }), encoding="utf-8")

            import io
            buf = io.StringIO()
            code = compare_experiments(["EXP-0010", "EXP-0011"], experiments_dir=tmp_path, as_json=True, output_stream=buf)
            self.assertEqual(code, 0)

            # Check safe_diff behavior directly
            self.assertIsNone(safe_diff(None, 100))
            self.assertIsNone(safe_diff(100, None))
            self.assertEqual(safe_diff(50.0, 75.5), 25.5)

    def test_08_missing_experiment_handling(self):
        """Test comparison error handling when experiment does not exist."""
        res = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "compare_experiments.py"), "EXP-9999", "EXP-0001"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("Experiment not found: EXP-9999", res.stderr)
        self.assertIn("Available experiments", res.stderr)
        self.assertNotIn("Traceback", res.stderr)

        # JSON error mode
        res_json = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "compare_experiments.py"), "EXP-9999", "EXP-0001", "--json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_json.returncode, 1)
        err_obj = json.loads(res_json.stdout)
        self.assertIn("error", err_obj)
        self.assertEqual(err_obj.get("missing_experiment"), "EXP-9999")

    def test_09_invalid_experiment_dir_handling(self):
        """Test manifest builder ignores invalid/corrupt experiment directories gracefully and reports them."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)

            # Invalid dir 1: empty directory
            inv1 = tmp_path / "EXP-CORRUPT"
            inv1.mkdir()

            # Invalid dir 2: missing metrics.json
            inv2 = tmp_path / "EXP-NOMETRICS"
            inv2.mkdir()
            (inv2 / "report.htm").write_text("dummy", encoding="utf-8")
            (inv2 / "metadata.json").write_text(json.dumps({"experiment_id": "EXP-NOMETRICS"}), encoding="utf-8")

            # Valid dir
            val_dir = tmp_path / "EXP-0001"
            val_dir.mkdir()
            (val_dir / "report.htm").write_text("Strategy Tester Report", encoding="utf-8")
            (val_dir / "metadata.json").write_text(json.dumps({
                "experiment_id": "EXP-0001",
                "ea": "TestEA",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "from": "2024.01.01",
                "to": "2024.02.01",
            }), encoding="utf-8")
            (val_dir / "metrics.json").write_text(json.dumps({
                "schema_version": 1,
                "settings": {"expert": "TestEA", "symbol": "GBPUSD", "timeframe": "M15"},
                "metrics": {
                    "history_quality_percent": 100.0,
                    "bars": 100,
                    "ticks": 500,
                    "total_net_profit": 10.0,
                    "profit_factor": 1.2,
                    "total_trades": 5,
                },
                "validation": {"test_executed": True}
            }), encoding="utf-8")

            out_manifest = tmp_path / "manifest.json"
            manifest = build_manifest(experiments_dir=tmp_path, output_path=out_manifest, quiet=True)

            self.assertEqual(manifest["total_experiments"], 1)
            self.assertEqual(manifest["experiments"][0]["id"], "EXP-0001")
            self.assertIn("invalid_experiments", manifest)
            self.assertEqual(len(manifest["invalid_experiments"]), 2)

    def test_10_research_period_classification(self):
        """Test classifying date ranges against configured research periods."""
        periods_cfg = {
            "schema_version": 1,
            "periods": {
                "training": {"from": "2023.01.01", "to": "2023.12.31"},
                "validation": {"from": "2024.01.01", "to": "2024.06.30"},
                "unseen": {"from": "2024.07.01", "to": "2024.12.31"},
            }
        }

        # Training
        dataset, status = classify_experiment_period("2023.02.01", "2023.05.01", periods_cfg)
        self.assertEqual(dataset, "training")
        self.assertEqual(status, "classified")

        # Validation
        dataset, status = classify_experiment_period("2024.01.01", "2024.02.01", periods_cfg)
        self.assertEqual(dataset, "validation")
        self.assertEqual(status, "classified")

        # Unseen
        dataset, status = classify_experiment_period("2024.08.01", "2024.10.01", periods_cfg)
        self.assertEqual(dataset, "unseen")
        self.assertEqual(status, "classified")

        # Out of bounds
        dataset, status = classify_experiment_period("2025.01.01", "2025.02.01", periods_cfg)
        self.assertIsNone(dataset)
        self.assertEqual(status, "out_of_bounds")

    def test_11_ambiguous_period_handling(self):
        """Test that date ranges overlapping multiple periods or crossing boundaries are marked ambiguous."""
        periods_cfg = {
            "schema_version": 1,
            "periods": {
                "training": {"from": "2023.01.01", "to": "2023.12.31"},
                "validation": {"from": "2024.01.01", "to": "2024.06.30"},
                "unseen": {"from": "2024.07.01", "to": "2024.12.31"},
            }
        }

        # Spans across training and validation
        dataset, status = classify_experiment_period("2023.11.01", "2024.02.01", periods_cfg)
        self.assertIsNone(dataset)
        self.assertEqual(status, "ambiguous")

        # Spans across validation and unseen
        dataset, status = classify_experiment_period("2024.06.15", "2024.07.15", periods_cfg)
        self.assertIsNone(dataset)
        self.assertEqual(status, "ambiguous")

        # Partial overlap (starts before training, ends inside training)
        dataset, status = classify_experiment_period("2022.12.01", "2023.03.01", periods_cfg)
        self.assertIsNone(dataset)
        self.assertEqual(status, "ambiguous")

    def test_12_unconfigured_period_handling(self):
        """Test unconfigured research periods."""
        unconfigured_cfg = {
            "schema_version": 1,
            "periods": {
                "training": {"from": None, "to": None},
                "validation": {"from": None, "to": None},
                "unseen": {"from": None, "to": None},
            }
        }
        dataset, status = classify_experiment_period("2024.01.01", "2024.02.01", unconfigured_cfg)
        self.assertIsNone(dataset)
        self.assertEqual(status, "unconfigured")

    def test_13_validation_rules(self):
        """Test data integrity checks in validation module."""
        # EXP-0001 should be valid
        res1 = validate_experiment_dir(self.exp1_dir)
        self.assertTrue(res1["is_valid"])
        self.assertEqual(len(res1["issues"]), 0)

        # Degraded experiment fixture
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "EXP-0099"
            tmp_path.mkdir()
            (tmp_path / "metadata.json").write_text(json.dumps({"experiment_id": "EXP-0099"}), encoding="utf-8")
            (tmp_path / "report.htm").write_text("", encoding="utf-8")  # Empty report
            (tmp_path / "metrics.json").write_text(json.dumps({
                "schema_version": 1,
                "metrics": {
                    "history_quality_percent": None,
                    "bars": 0,  # 0 bars
                    "ticks": 0,  # 0 ticks
                },
                "validation": {"test_executed": False}
            }), encoding="utf-8")

            val = validate_experiment_dir(tmp_path)
            self.assertFalse(val["is_valid"])
            self.assertFalse(val["checks"]["report_non_empty"])
            self.assertFalse(val["checks"]["bars_positive"])
            self.assertFalse(val["checks"]["ticks_positive"])
            self.assertFalse(val["checks"]["history_quality_present"])
            self.assertFalse(val["checks"]["test_executed"])

    def test_14_incremental_indexing_preserves_existing(self):
        """Test that adding a new experiment indexes it without changing existing EXP-0001 or EXP-0002."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # Copy real EXP-0001 and EXP-0002 into fixture
            shutil.copytree(self.exp1_dir, tmp_path / "EXP-0001")
            shutil.copytree(self.exp2_dir, tmp_path / "EXP-0002")

            # Generate initial manifest
            m1 = build_manifest(experiments_dir=tmp_path, output_path=tmp_path / "manifest.json", quiet=True)
            self.assertEqual(m1["total_experiments"], 2)

            # Add simulated EXP-0003
            exp3 = tmp_path / "EXP-0003"
            shutil.copytree(self.exp2_dir, exp3)
            meta3 = json.loads((exp3 / "metadata.json").read_text(encoding="utf-8"))
            meta3["experiment_id"] = "EXP-0003"
            meta3["note"] = "Experiment Intelligence integration verification"
            (exp3 / "metadata.json").write_text(json.dumps(meta3), encoding="utf-8")

            # Rebuild manifest
            m2 = build_manifest(experiments_dir=tmp_path, output_path=tmp_path / "manifest.json", quiet=True)
            self.assertEqual(m2["total_experiments"], 3)
            ids = [e["id"] for e in m2["experiments"]]
            self.assertEqual(ids, ["EXP-0001", "EXP-0002", "EXP-0003"])

            # Verify EXP-0001 and EXP-0002 entries did not change
            self.assertEqual(m1["experiments"][0], m2["experiments"][0])
            self.assertEqual(m1["experiments"][1], m2["experiments"][1])

    def test_15_configured_research_periods_integrity(self):
        """Test configured research periods integrity: training, validation, unseen, dates, chronology, non-overlap, boundaries."""
        periods_cfg = load_research_periods()
        self.assertTrue(is_periods_configured(periods_cfg))
        self.assertEqual(periods_cfg.get("status"), "configured")

        # 1-3. Verify training, validation, unseen exist
        periods = periods_cfg.get("periods", {})
        self.assertIn("training", periods)
        self.assertIn("validation", periods)
        self.assertIn("unseen", periods)

        # 4. Verify dates are valid
        train_from = parse_date(periods["training"]["from"])
        train_to = parse_date(periods["training"]["to"])
        val_from = parse_date(periods["validation"]["from"])
        val_to = parse_date(periods["validation"]["to"])
        unseen_from = parse_date(periods["unseen"]["from"])
        unseen_to = parse_date(periods["unseen"]["to"])

        self.assertIsNotNone(train_from)
        self.assertIsNotNone(train_to)
        self.assertIsNotNone(val_from)
        self.assertIsNotNone(val_to)
        self.assertIsNotNone(unseen_from)
        self.assertIsNotNone(unseen_to)

        self.assertLessEqual(train_from, train_to)
        self.assertLessEqual(val_from, val_to)
        self.assertLessEqual(unseen_from, unseen_to)

        # Exact date bounds as specified
        self.assertEqual(str(train_from), "2020-01-01")
        self.assertEqual(str(train_to), "2024-12-31")
        self.assertEqual(str(val_from), "2025-01-01")
        self.assertEqual(str(val_to), "2025-12-31")
        self.assertEqual(str(unseen_from), "2026-01-01")
        self.assertEqual(str(unseen_to), "2026-09-30")

        # 5. Chronological order
        self.assertLess(train_to, val_from)
        self.assertLess(val_to, unseen_from)

        # 6. No overlap & 7. Boundary correctness
        valid, issues = validate_research_periods_integrity(periods_cfg)
        self.assertTrue(valid, f"Integrity issues found: {issues}")
        self.assertEqual(len(issues), 0)


if __name__ == "__main__":
    unittest.main()
