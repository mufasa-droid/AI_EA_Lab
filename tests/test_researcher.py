"""
Automated Test Suite for AI EA Lab - AI Researcher & Experiment Planner

Tests:
1. Research context generation.
2. Hypothesis schema validation.
3. Experiment-plan schema validation.
4. Historical experiment lookup.
5. Missing experiment handling.
6. Missing metric handling.
7. Unconfigured research periods handling.
8. Duplicate experiment detection.
9. Baseline references in plan.
10. Fact vs hypothesis separation.
11. Rejection of fabricated experiment IDs.
12. Deterministic mock researcher output.
13. JSON output validity.
14. Human-readable proposal generation.
15. Multiple simultaneous changes warning.
16. Existing experiments (EXP-0001, EXP-0002) remain untouched.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.experiment_planner import create_experiment_plan, save_experiment_plan
from scripts.research_context import (
    build_research_context,
    check_duplicate_configuration,
    get_historical_experiment_details,
    save_research_context,
)
from scripts.research_schemas import (
    get_next_hypothesis_id,
    get_next_plan_id,
    validate_experiment_plan_dict,
    validate_hypothesis_dict,
)
from scripts.researcher import (
    format_human_proposal,
    formulate_mock_hypothesis,
    run_researcher,
)


class TestAIResearcher(unittest.TestCase):

    def setUp(self):
        self.experiments_dir = PROJECT_ROOT / "experiments"
        self.exp1_dir = self.experiments_dir / "EXP-0001"
        self.exp2_dir = self.experiments_dir / "EXP-0002"

    def test_01_research_context_generation(self):
        """Test unified research context generation from active repository."""
        ctx = build_research_context()
        self.assertEqual(ctx.get("schema_version"), 1)
        self.assertIn("generated_at", ctx)

        # Project state
        ps = ctx.get("project_state", {})
        self.assertEqual(ps.get("ea_name"), "TestEA")
        self.assertEqual(ps.get("symbol"), "GBPUSD")
        latest_id = ps.get("latest_experiment_id", "")
        self.assertTrue(latest_id.startswith("EXP-"))
        self.assertGreaterEqual(int(latest_id.split("-")[1]), 2)

        # Historical experiments
        hist = ctx.get("historical_experiments", [])
        exp_ids = [e["id"] for e in hist]
        self.assertIn("EXP-0001", exp_ids)
        self.assertIn("EXP-0002", exp_ids)

        # Constraints
        constraints = ctx.get("constraints", {})
        self.assertTrue(constraints.get("no_live_trading"))
        self.assertTrue(constraints.get("no_fabricated_data"))
        self.assertTrue(constraints.get("human_approval_required"))

    def test_02_hypothesis_schema_validation(self):
        """Test hypothesis schema validation with valid and invalid data."""
        ctx = build_research_context()
        valid_hyp = formulate_mock_hypothesis(ctx)
        is_valid, issues = validate_hypothesis_dict(valid_hyp)
        self.assertTrue(is_valid, f"Valid hypothesis failed: {issues}")
        self.assertEqual(len(issues), 0)

        # Missing basis facts
        corrupt_hyp = dict(valid_hyp)
        corrupt_hyp["basis"] = {"historical_experiments": ["EXP-0002"], "facts": []}
        is_val, issues = validate_hypothesis_dict(corrupt_hyp)
        self.assertFalse(is_val)
        self.assertTrue(any("facts" in i for i in issues))

        # Missing independent variables
        corrupt_hyp2 = dict(valid_hyp)
        corrupt_hyp2["independent_variables"] = []
        is_val2, issues2 = validate_hypothesis_dict(corrupt_hyp2)
        self.assertFalse(is_val2)
        self.assertTrue(any("independent variable" in i for i in issues2))

    def test_03_experiment_plan_schema_validation(self):
        """Test experiment plan schema validation with valid and invalid data."""
        ctx = build_research_context()
        hyp = formulate_mock_hypothesis(ctx)
        plan = create_experiment_plan(hyp, ctx)

        is_valid, issues = validate_experiment_plan_dict(plan)
        self.assertTrue(is_valid, f"Valid plan failed: {issues}")

        # Missing human_review_required
        corrupt_plan = dict(plan)
        corrupt_plan["human_review_required"] = False
        is_val, issues = validate_experiment_plan_dict(corrupt_plan)
        self.assertFalse(is_val)
        self.assertTrue(any("human_review_required" in i for i in issues))

    def test_04_historical_experiment_lookup(self):
        """Test retrieving rich details of verified historical experiments."""
        details1 = get_historical_experiment_details("EXP-0001")
        self.assertIsNotNone(details1)
        self.assertEqual(details1["id"], "EXP-0001")
        self.assertEqual(details1["ea"], "TestEA")
        self.assertEqual(details1["symbol"], "GBPUSD")
        self.assertEqual(details1["inputs"].get("FastMAPeriod"), "10")
        self.assertEqual(details1["inputs"].get("SlowMAPeriod"), "20")
        self.assertEqual(details1["trading"]["total_trades"], 0)
        self.assertEqual(details1["data_quality"]["bars"], 2120)

    def test_05_missing_experiment_handling(self):
        """Test that looking up a non-existent experiment returns None cleanly."""
        missing = get_historical_experiment_details("EXP-9999")
        self.assertIsNone(missing)

        # Baseline resolution with missing experiment
        ctx = build_research_context()
        with self.assertRaises(FileNotFoundError):
            formulate_mock_hypothesis(ctx, baseline_id="EXP-9999")

    def test_06_missing_metric_handling(self):
        """Test handling of experiments with sparse or missing metrics."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            e_dir = tmp_path / "EXP-0050"
            e_dir.mkdir()
            (e_dir / "metadata.json").write_text(json.dumps({
                "experiment_id": "EXP-0050",
                "ea": "SparseEA",
                "symbol": "EURUSD",
                "inputs": {"Period": "14"},
            }), encoding="utf-8")
            (e_dir / "metrics.json").write_text(json.dumps({
                "schema_version": 1,
                "settings": {"expert": "SparseEA"},
                "metrics": {},  # completely empty metrics
            }), encoding="utf-8")

            details = get_historical_experiment_details("EXP-0050", experiments_dir=tmp_path)
            self.assertIsNotNone(details)
            self.assertIsNone(details["performance"]["total_net_profit"])
            self.assertIsNone(details["trading"]["total_trades"])

    def test_07_unconfigured_research_periods(self):
        """Test unconfigured research periods are handled safely without invention."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            unconfigured_path = Path(tmp_dir) / "research_periods.json"
            unconfigured_path.write_text(json.dumps({
                "schema_version": 1,
                "status": "unconfigured",
                "periods": {
                    "training": {"from": None, "to": None},
                    "validation": {"from": None, "to": None},
                    "unseen": {"from": None, "to": None},
                }
            }), encoding="utf-8")
            ctx = build_research_context(periods_path=unconfigured_path)
            self.assertFalse(ctx["research_periods"]["is_configured"])
            self.assertEqual(ctx["research_periods"]["status"], "unconfigured")

            hyp = formulate_mock_hypothesis(ctx)
            self.assertEqual(hyp["dataset"]["status"], "unconfigured")

            plan = create_experiment_plan(hyp, ctx)
            self.assertEqual(plan["dataset"]["status"], "unconfigured")
            self.assertIn("unconfigured placeholders", plan["dataset"]["note"])

    def test_08_duplicate_experiment_detection(self):
        """Test detection of duplicate experiment parameter configurations."""
        ctx = build_research_context()

        # Propose identical inputs to EXP-0001 / EXP-0002
        dup_inputs = {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"}
        dup_id = check_duplicate_configuration(
            proposed_inputs=dup_inputs,
            ea="TestEA",
            symbol="GBPUSD",
            timeframe="M15",
            context=ctx,
        )
        self.assertIsNotNone(dup_id)
        self.assertIn(dup_id, ["EXP-0001", "EXP-0002"])

        # Check planner attaches duplicate warning
        hyp = formulate_mock_hypothesis(ctx, baseline_id="EXP-0002")
        # Force hypothesis to propose the duplicate inputs
        hyp["independent_variables"] = [{
            "name": "FastMAPeriod",
            "baseline_value": "10",
            "proposed_value": "10",
        }]
        plan = create_experiment_plan(hyp, ctx, baseline_id="EXP-0002")
        self.assertTrue(any("duplicate" in w.lower() for w in plan["warnings"]))

    def test_09_baseline_references(self):
        """Test that the experiment plan correctly references baseline experiment and variables."""
        ctx = build_research_context()
        hyp = formulate_mock_hypothesis(ctx, baseline_id="EXP-0002")
        plan = create_experiment_plan(hyp, ctx, baseline_id="EXP-0002")

        self.assertEqual(plan["baseline"]["experiment_id"], "EXP-0002")
        self.assertEqual(plan["baseline"]["inputs"]["FastMAPeriod"], "10")

        # Verify unchanged control variables
        unchanged_keys = [u["variable"] for u in plan["unchanged_variables"]]
        self.assertIn("SlowMAPeriod", unchanged_keys)
        self.assertIn("LotSize", unchanged_keys)
        self.assertNotIn("FastMAPeriod", unchanged_keys)

    def test_10_fact_vs_hypothesis_separation(self):
        """Test strict separation between facts, inferences, hypotheses, and expected observations."""
        ctx = build_research_context()
        hyp = formulate_mock_hypothesis(ctx, baseline_id="EXP-0002")

        # Facts must contain direct observations from historical tests
        facts = hyp["basis"]["facts"]
        self.assertTrue(any("recorded exactly 0 trades" in f for f in facts))

        # Inferences must contain deductions
        inferences = hyp["basis"]["inferences"]
        self.assertTrue(len(inferences) > 0)

        # Hypothesis must express a testable proposition with uncertainty
        hyp_text = hyp["hypothesis"]
        self.assertIn("will increase signal sensitivity and result in more than 0 trades", hyp_text)

        # Expected observations must describe measurable outcomes
        exp_obs = hyp["expected_observations"]
        self.assertTrue(any("increase from 0" in o for o in exp_obs))

        # Falsification conditions must describe outcomes that weaken the hypothesis
        fals = hyp["falsification_conditions"]
        self.assertTrue(any("remain exactly 0" in fc for fc in fals))

    def test_11_no_fabricated_experiment_ids(self):
        """Test that all historical experiments cited in hypothesis basis exist in archive."""
        ctx = build_research_context()
        hyp = formulate_mock_hypothesis(ctx)

        manifest_ids = [e["id"] for e in ctx["historical_experiments"]]
        for cited_id in hyp["basis"]["historical_experiments"]:
            self.assertIn(cited_id, manifest_ids, f"Fabricated experiment cited: {cited_id}")

    def test_12_deterministic_mock_researcher(self):
        """Test that mock researcher execution is deterministic across runs."""
        ctx = build_research_context()
        h1 = formulate_mock_hypothesis(ctx)
        h2 = formulate_mock_hypothesis(ctx)

        self.assertEqual(h1["research_question"], h2["research_question"])
        self.assertEqual(h1["hypothesis"], h2["hypothesis"])
        self.assertEqual(h1["independent_variables"], h2["independent_variables"])
        self.assertEqual(h1["expected_observations"], h2["expected_observations"])

    def test_13_json_output_validity(self):
        """Test CLI JSON output mode."""
        res = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "researcher.py"), "--mock", "--json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"CLI error: {res.stderr}")
        data = json.loads(res.stdout)

        self.assertEqual(data.get("schema_version"), 1)
        self.assertEqual(data.get("researcher_mode"), "mock")
        self.assertIn("hypothesis", data)
        self.assertIn("experiment_plan", data)

        is_hyp_valid, _ = validate_hypothesis_dict(data["hypothesis"])
        self.assertTrue(is_hyp_valid)

        is_plan_valid, _ = validate_experiment_plan_dict(data["experiment_plan"])
        self.assertTrue(is_plan_valid)

    def test_14_human_readable_proposal_generation(self):
        """Test CLI human-readable research proposal formatting."""
        res = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "researcher.py"), "--mock"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        output = res.stdout

        self.assertIn("AI RESEARCH PROPOSAL", output)
        self.assertIn("[MODE: MOCK RESEARCHER", output)
        self.assertIn("--- RESEARCH QUESTION ---", output)
        self.assertIn("--- OBSERVED FACTS (Historical Evidence) ---", output)
        self.assertIn("--- INFERENCES (Logical Deductions) ---", output)
        self.assertIn("--- HYPOTHESIS (Testable Proposition) ---", output)
        self.assertIn("--- EXPERIMENT DESIGN ---", output)
        self.assertIn("--- EXPECTED OBSERVATIONS ---", output)
        self.assertIn("--- FALSIFICATION CONDITIONS ---", output)
        self.assertIn("--- OPERATIONAL BOUNDARY ---", output)
        self.assertIn("PLANNED (Human Review Required)", output)

    def test_15_multiple_change_warning(self):
        """Test that modifying multiple independent variables produces a causal attribution warning."""
        ctx = build_research_context()
        hyp = formulate_mock_hypothesis(ctx)

        # Inject 2 independent variables changing at once
        hyp["independent_variables"] = [
            {"name": "FastMAPeriod", "baseline_value": "10", "proposed_value": "5"},
            {"name": "SlowMAPeriod", "baseline_value": "20", "proposed_value": "30"},
        ]

        plan = create_experiment_plan(hyp, ctx)
        warnings = plan.get("warnings", [])
        self.assertTrue(any("Multiple independent variables" in w for w in warnings))

    def test_16_existing_experiments_remain_untouched(self):
        """Test that running the Researcher does not alter EXP-0001 or EXP-0002."""
        self.assertTrue(self.exp1_dir.exists())
        self.assertTrue(self.exp2_dir.exists())

        meta1 = json.loads((self.exp1_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta1["experiment_id"], "EXP-0001")

        meta2 = json.loads((self.exp2_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta2["experiment_id"], "EXP-0002")
        self.assertEqual(meta2["note"], "Verification of EXP-0002 preservation")


if __name__ == "__main__":
    unittest.main()
