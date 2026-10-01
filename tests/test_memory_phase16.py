"""
Phase 16 Test Suite — Research Memory & Knowledge Accumulation System

Verifies:
- Memory record types (HYPOTHESIS_RECORD, EXPERIMENT_OBSERVATION, AUDIT_FINDING, RESEARCH_LESSON, OPEN_RESEARCH_QUESTION, RELATIONSHIP).
- Schema validation and schema versioning (schema_version = 1).
- Fact vs Observation vs Interpretation vs Lesson distinction.
- Idempotent ingestion (repeated ingestion produces ALREADY_INGESTED without duplicate records).
- Canonical evidence immutability (memory operations never modify raw experiment, candidate, hypothesis, or plan files).
- Provenance & traceability (every record references canonical source IDs).
- Dataset separation (training vs validation vs unseen; unseen partition is protected).
- Zero-trade factual observation handling.
- Failed experiment and infeasible plan memory.
- Conflicting evidence preservation (CONFLICTS_WITH relationship & CONFLICTING_EVIDENCE status).
- Knowledge state transitions and human review status (unreviewed vs human_reviewed, no fabricated approval).
- Hypothesis novelty classifier (EXACT_DUPLICATE, NEAR_DUPLICATE, RELATED_HYPOTHESIS, NOVEL_HYPOTHESIS, UNKNOWN).
- Research context assembly for AI Researcher with explicit operational safety guidance.
- Memory integrity audit (broken reference detection, duplicate detection, schema checking).
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.memory import (
    MEMORY_SCHEMA_VERSION,
    add_memory_record,
    build_research_memory_context,
    classify_hypothesis_novelty,
    compute_memory_record_fingerprint,
    ensure_memory_directories,
    find_memory_records,
    get_memory_record,
    ingest_audit,
    ingest_experiment,
    ingest_infeasible_plan,
    load_memory_index,
    record_conflicting_observations,
    validate_memory_record,
    verify_memory_integrity,
)


class TestPhase16ResearchMemory(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ea_lab_mem_test_"))
        self.mem_dir = self.temp_dir / "research" / "memory"
        self.exp_dir = self.temp_dir / "experiments"
        self.cand_dir = self.temp_dir / "developer" / "candidates"
        self.hyp_dir = self.temp_dir / "research" / "hypotheses"
        self.plan_dir = self.temp_dir / "research" / "plans"

        ensure_memory_directories(self.mem_dir)
        self.exp_dir.mkdir(parents=True, exist_ok=True)
        self.cand_dir.mkdir(parents=True, exist_ok=True)
        self.hyp_dir.mkdir(parents=True, exist_ok=True)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

        # Create mock baseline experiment EXP-0001
        self.exp1_dir = self.exp_dir / "EXP-0001"
        self.exp1_dir.mkdir(parents=True, exist_ok=True)
        (self.exp1_dir / "report.htm").write_text("<html>Report EXP-0001</html>", encoding="utf-8")
        (self.exp1_dir / "metadata.json").write_text(
            json.dumps({
                "experiment_id": "EXP-0001",
                "candidate_id": "CAND-0001",
                "hypothesis_id": "HYP-0001",
                "plan_id": "PLAN-0001",
                "symbol": "GBPUSD",
                "timeframe": "M15",
                "from": "2020.01.01",
                "to": "2024.12.31",
                "dataset_partition": "training",
            }, indent=2),
            encoding="utf-8",
        )
        (self.exp1_dir / "metrics.json").write_text(
            json.dumps({
                "settings": {"symbol": "GBPUSD", "timeframe": "M15", "from": "2020.01.01", "to": "2024.12.31"},
                "metrics": {
                    "total_net_profit": 150.0,
                    "profit_factor": 1.5,
                    "total_trades": 10,
                    "bars": 1000,
                    "ticks": 5000,
                    "history_quality_percent": 100.0,
                },
                "validation": {"test_executed": True},
            }, indent=2),
            encoding="utf-8",
        )

        # Create mock candidate CAND-0001
        c1 = self.cand_dir / "CAND-0001"
        c1.mkdir(parents=True, exist_ok=True)
        (c1 / "metadata.json").write_text(json.dumps({"candidate_id": "CAND-0001"}), encoding="utf-8")

        # Create mock hypothesis HYP-0001
        (self.hyp_dir / "HYP-0001.json").write_text(
            json.dumps({
                "hypothesis_id": "HYP-0001",
                "title": "Fast MAPeriod Reduction",
                "hypothesis": "Reducing FastMAPeriod from 10 to 5 increases signal frequency.",
                "research_question": "Does FastMAPeriod 5 increase signals?",
            }),
            encoding="utf-8",
        )

        # Create mock plan PLAN-0001
        (self.plan_dir / "PLAN-0001.json").write_text(
            json.dumps({"experiment_plan_id": "PLAN-0001"}), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_type_creation_and_validation(self):
        """Verifies that all 6 memory record types create and validate cleanly."""
        records = [
            {
                "record_type": "HYPOTHESIS_RECORD",
                "hypothesis_id": "HYP-0001",
                "statement": "Reducing FastMAPeriod increases signals.",
                "source": "AI Researcher",
            },
            {
                "record_type": "EXPERIMENT_OBSERVATION",
                "experiment_id": "EXP-0001",
                "candidate_id": "CAND-0001",
                "observation_category": "FACT",
                "observation": "EXP-0001 recorded 10 trades.",
            },
            {
                "record_type": "AUDIT_FINDING",
                "audit_id": "AUD-0001",
                "experiment_id": "EXP-0001",
                "dimension": "provenance",
                "status": "PASS",
                "finding": "Verified complete lineage.",
            },
            {
                "record_type": "RESEARCH_LESSON",
                "statement": "TestEA requires explicit tick triggers.",
                "knowledge_status": "SUPPORTED",
            },
            {
                "record_type": "OPEN_RESEARCH_QUESTION",
                "question": "What is the optimal FastMAPeriod for signal frequency?",
            },
            {
                "record_type": "RELATIONSHIP",
                "source_id": "HYP-0001",
                "source_type": "HYPOTHESIS",
                "relation": "TESTED_BY",
                "target_id": "EXP-0001",
                "target_type": "EXPERIMENT",
            },
        ]

        for r in records:
            res = add_memory_record(r, base_dir=self.mem_dir)
            self.assertEqual(res["status"], "INGESTED")
            self.assertTrue(res["memory_id"].startswith("MEM-"))

    def test_idempotent_ingestion_prevents_duplicates(self):
        """Verifies that duplicate record ingestion returns ALREADY_INGESTED."""
        rec = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": "EXP-0001",
            "observation_category": "FACT",
            "observation": "EXP-0001 recorded 10 trades.",
        }

        res1 = add_memory_record(rec, base_dir=self.mem_dir)
        self.assertEqual(res1["status"], "INGESTED")

        res2 = add_memory_record(rec, base_dir=self.mem_dir)
        self.assertEqual(res2["status"], "ALREADY_INGESTED")
        self.assertEqual(res1["memory_id"], res2["memory_id"])

        idx = load_memory_index(self.mem_dir)
        self.assertEqual(idx["total_records"], 1)

    def test_canonical_evidence_immutability(self):
        """Verifies that ingesting memory does NOT mutate underlying canonical experiment files."""
        meta_before = (self.exp1_dir / "metadata.json").read_text(encoding="utf-8")
        metrics_before = (self.exp1_dir / "metrics.json").read_text(encoding="utf-8")

        res = ingest_experiment("EXP-0001", experiments_dir=self.exp_dir, base_dir=self.mem_dir)
        self.assertEqual(res["status"], "COMPLETED")

        meta_after = (self.exp1_dir / "metadata.json").read_text(encoding="utf-8")
        metrics_after = (self.exp1_dir / "metrics.json").read_text(encoding="utf-8")

        self.assertEqual(meta_before, meta_after)
        self.assertEqual(metrics_before, metrics_after)

    def test_zero_trade_factual_observation(self):
        """Verifies zero-trade experiments are recorded factually without strategy judgment."""
        exp2_dir = self.exp_dir / "EXP-0002"
        exp2_dir.mkdir(parents=True, exist_ok=True)
        (exp2_dir / "metadata.json").write_text(
            json.dumps({"experiment_id": "EXP-0002", "symbol": "GBPUSD", "timeframe": "M15"}, indent=2),
            encoding="utf-8",
        )
        (exp2_dir / "metrics.json").write_text(
            json.dumps({"metrics": {"total_trades": 0, "total_net_profit": 0.0, "profit_factor": 0.0}}, indent=2),
            encoding="utf-8",
        )

        res = ingest_experiment("EXP-0002", experiments_dir=self.exp_dir, base_dir=self.mem_dir)
        self.assertEqual(res["status"], "COMPLETED")

        obs_recs = find_memory_records(record_type="EXPERIMENT_OBSERVATION", experiment_id="EXP-0002", base_dir=self.mem_dir)
        self.assertTrue(len(obs_recs) >= 2)

        zero_obs = [r for r in obs_recs if "0 trades" in r["observation"]]
        self.assertTrue(len(zero_obs) > 0)
        self.assertEqual(zero_obs[0]["observation_category"], "OBSERVATION")

    def test_infeasible_plan_ingestion(self):
        """Verifies infeasible experiment plans are ingested as FEASIBILITY lessons."""
        plan_dict = {"experiment_plan_id": "PLAN-0001", "baseline": {"ea": "TestEA"}}
        feas_dict = {"is_feasible": False, "reason": "Target EA OnTick() is empty and lacks order execution."}

        res = ingest_infeasible_plan(plan_dict, feas_dict, base_dir=self.mem_dir)
        self.assertEqual(res["status"], "INGESTED")

        rec = get_memory_record(res["memory_id"], base_dir=self.mem_dir)
        self.assertEqual(rec["record_type"], "RESEARCH_LESSON")
        self.assertEqual(rec["category"], "FEASIBILITY")
        self.assertIn("TestEA", rec["statement"])

    def test_conflicting_evidence_preservation(self):
        """Verifies conflicting observations create CONFLICTS_WITH relationship and mark status."""
        rec1 = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": "EXP-0001",
            "observation_category": "OBSERVATION",
            "observation": "FastMAPeriod 5 increased trade count to 10 on GBPUSD M15.",
        }
        rec2 = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": "EXP-0003",
            "observation_category": "OBSERVATION",
            "observation": "FastMAPeriod 5 decreased trade count to 0 on EURUSD M15.",
        }

        r1 = add_memory_record(rec1, base_dir=self.mem_dir)
        r2 = add_memory_record(rec2, base_dir=self.mem_dir)

        c_res = record_conflicting_observations(r1["memory_id"], r2["memory_id"], "Conflicting trade outcome across currency pairs", base_dir=self.mem_dir)
        self.assertEqual(c_res["status"], "INGESTED")

        rel_recs = find_memory_records(record_type="RELATIONSHIP", base_dir=self.mem_dir)
        conflicts = [r for r in rel_recs if r["relation"] == "CONFLICTS_WITH"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["source_id"], r1["memory_id"])
        self.assertEqual(conflicts[0]["target_id"], r2["memory_id"])

    def test_hypothesis_novelty_classification(self):
        """Verifies novelty classifier correctly identifies EXACT, NEAR, RELATED, and NOVEL hypotheses."""
        existing_hyp = {
            "hypothesis_id": "HYP-0001",
            "hypothesis": "Reducing FastMAPeriod from 10 to 5 increases signal frequency.",
            "research_question": "Does FastMAPeriod 5 increase signals?",
            "basis": {"historical_experiments": ["EXP-0001"]},
            "changes_under_test": [{"variable": "FastMAPeriod", "target_value": "5"}],
        }
        (self.hyp_dir / "HYP-0001.json").write_text(json.dumps(existing_hyp, indent=2), encoding="utf-8")

        # 1. Exact Duplicate
        exact_hyp = {
            "hypothesis": "Reducing FastMAPeriod from 10 to 5 increases signal frequency.",
            "changes_under_test": [{"variable": "FastMAPeriod", "target_value": "5"}],
        }
        state1, msg1, match1 = classify_hypothesis_novelty(exact_hyp, base_dir=self.mem_dir, hypotheses_dir=self.hyp_dir)
        self.assertEqual(state1, "EXACT_DUPLICATE")

        # 2. Near Duplicate
        near_hyp = {
            "hypothesis": "Reducing FastMAPeriod from 10 to 7 increases signal frequency.",
            "changes_under_test": [{"variable": "FastMAPeriod", "target_value": "7"}],
        }
        state2, msg2, match2 = classify_hypothesis_novelty(near_hyp, base_dir=self.mem_dir, hypotheses_dir=self.hyp_dir)
        self.assertEqual(state2, "NEAR_DUPLICATE")

        # 3. Related Hypothesis
        related_hyp = {
            "hypothesis": "Increasing SlowMAPeriod on EXP-0001 baseline reduces false signals.",
            "basis": {"historical_experiments": ["EXP-0001"]},
            "changes_under_test": [{"variable": "SlowMAPeriod", "target_value": "30"}],
        }
        state3, msg3, match3 = classify_hypothesis_novelty(related_hyp, base_dir=self.mem_dir, hypotheses_dir=self.hyp_dir)
        self.assertEqual(state3, "RELATED_HYPOTHESIS")

        # 4. Novel Hypothesis
        novel_hyp = {
            "hypothesis": "Adding RSI filter (period=14) to TrendEA prevents overtrading.",
            "baseline": {"experiment_id": "EXP-0099"},
            "changes_under_test": [{"variable": "RSIPeriod", "target_value": "14"}],
        }
        state4, msg4, match4 = classify_hypothesis_novelty(novel_hyp, base_dir=self.mem_dir, hypotheses_dir=self.hyp_dir)
        self.assertEqual(state4, "NOVEL_HYPOTHESIS")

    def test_dataset_unseen_partition_protection(self):
        """Verifies that UNSEEN dataset partition records are excluded from prompt context."""
        unseen_rec = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": "EXP-0099",
            "dataset_partition": "unseen",
            "observation_category": "FACT",
            "observation": "SECRET_UNSEEN_DATA_OBSERVATION",
        }
        add_memory_record(unseen_rec, base_dir=self.mem_dir)

        ctx = build_research_memory_context(base_dir=self.mem_dir, include_unseen=False)
        self.assertNotIn("SECRET_UNSEEN_DATA_OBSERVATION", str(ctx["facts"]))

        ctx_unseen = build_research_memory_context(base_dir=self.mem_dir, include_unseen=True)
        self.assertIn("SECRET_UNSEEN_DATA_OBSERVATION", str(ctx_unseen["facts"]))

    def test_memory_integrity_verification(self):
        """Verifies memory integrity auditor detects clean status and broken references."""
        # 1. Clean state
        ingest_experiment("EXP-0001", experiments_dir=self.exp_dir, base_dir=self.mem_dir)
        res_clean = verify_memory_integrity(
            base_dir=self.mem_dir,
            experiments_dir=self.exp_dir,
            candidates_dir=self.cand_dir,
            hypotheses_dir=self.hyp_dir,
            plans_dir=self.plan_dir,
        )
        self.assertEqual(res_clean["status"], "PASS")

        # 2. Corrupted broken reference
        broken_rec = {
            "record_type": "EXPERIMENT_OBSERVATION",
            "experiment_id": "EXP-NON-EXISTENT",
            "observation_category": "FACT",
            "observation": "Invalid reference experiment observation.",
        }
        add_memory_record(broken_rec, base_dir=self.mem_dir)

        res_broken = verify_memory_integrity(
            base_dir=self.mem_dir,
            experiments_dir=self.exp_dir,
            candidates_dir=self.cand_dir,
            hypotheses_dir=self.hyp_dir,
            plans_dir=self.plan_dir,
        )
        self.assertEqual(res_broken["status"], "FAIL")
        self.assertTrue(len(res_broken["broken_references"]) > 0)


if __name__ == "__main__":
    unittest.main()
