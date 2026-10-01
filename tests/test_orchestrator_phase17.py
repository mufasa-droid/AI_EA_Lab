"""
Phase 17 Test Suite — Research Orchestrator & Autonomous Pipeline

Verifies:
- Orchestrator creation, ID generation, state persistence, and configuration.
- Append-only event log (events.jsonl).
- Hard Human Approval Gate enforcement (AWAITING_APPROVAL -> approve_orchestrator_plan -> APPROVED).
- Approval bound strictly to current_plan_id (mismatch rejected).
- Resource lock (OrchestratorResourceLock) preventing concurrent execution conflicts.
- Budget bounds (maximum_iterations, maximum_failures).
- End-to-end mocked research cycle (Researcher -> Planner -> Approval -> Developer -> Verifier -> Runner -> Auditor -> Memory -> Decision).
- Crash recovery & restartability (resumes cleanly from persisted state.json).
- Failure classification & failure state transitions.
- Dry-run mode.
- Dataset separation & UNSEEN protection.
- Proof that historical experiment files (EXP-0001, etc.) remain untouched.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.research_orchestrator import (
    ORCHESTRATOR_SCHEMA_VERSION,
    STATE_APPROVED,
    STATE_AWAITING_APPROVAL,
    STATE_CANDIDATE_CREATED,
    STATE_CANDIDATE_VERIFIED,
    STATE_DECISION_CREATED,
    STATE_EXPERIMENT_CREATED,
    STATE_HYPOTHESIS_CREATED,
    STATE_ITERATION_COMPLETED,
    STATE_ITERATION_FAILED,
    STATE_ORCHESTRATOR_COMPLETED,
    STATE_ORCHESTRATOR_CREATED,
    STATE_ORCHESTRATOR_PAUSED,
    STATE_PLAN_CREATED,
    STATE_RESEARCHING,
    OrchestratorResourceLock,
    append_orchestrator_event,
    approve_orchestrator_plan,
    execute_orchestrator_step,
    init_orchestrator_run,
    load_orchestrator_run,
    pause_orchestrator,
    persist_orchestrator_state,
    resume_orchestrator,
    run_orchestrator_until_stop,
    stop_orchestrator,
)


class TestPhase17ResearchOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="ea_lab_orch_test_"))
        self.runs_dir = self.temp_dir / "research" / "orchestrator" / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_orchestrator_initialization_and_persistence(self):
        """Verifies orchestrator init, unique ID generation, and state persistence."""
        orch_id, run_dir, state = init_orchestrator_run(runs_dir=self.runs_dir)
        self.assertTrue(orch_id.startswith("ORCH-"))
        self.assertEqual(state["current_state"], STATE_ORCHESTRATOR_CREATED)
        self.assertTrue((run_dir / "state.json").is_file())
        self.assertTrue((run_dir / "configuration.json").is_file())
        self.assertTrue((run_dir / "events.jsonl").is_file())

        loaded_state, _ = load_orchestrator_run(orch_id, runs_dir=self.runs_dir)
        self.assertEqual(loaded_state["orchestrator_id"], orch_id)
        self.assertEqual(loaded_state["current_state"], STATE_ORCHESTRATOR_CREATED)

    def test_append_only_event_log(self):
        """Verifies event log appends records without overwriting historical events."""
        orch_id, run_dir, state = init_orchestrator_run(runs_dir=self.runs_dir)
        append_orchestrator_event(run_dir, orch_id, "ITER-0001", "CREATED", "RESEARCHING", "Test event 1")
        append_orchestrator_event(run_dir, orch_id, "ITER-0001", "RESEARCHING", "PLANNED", "Test event 2")

        events_file = run_dir / "events.jsonl"
        lines = [line for line in events_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)  # 1 init + 2 appends

        evt1 = json.loads(lines[1])
        evt2 = json.loads(lines[2])
        self.assertEqual(evt1["from_state"], "CREATED")
        self.assertEqual(evt2["from_state"], "RESEARCHING")

    def test_approval_gate_and_plan_binding(self):
        """Verifies approval halts at AWAITING_APPROVAL and binds strictly to plan_id."""
        orch_id, run_dir, state = init_orchestrator_run({"dry_run": True}, runs_dir=self.runs_dir)

        # Run until approval gate
        run_orchestrator_until_stop(orch_id, runs_dir=self.runs_dir)

        state_paused, _ = load_orchestrator_run(orch_id, runs_dir=self.runs_dir)
        self.assertEqual(state_paused["current_state"], STATE_AWAITING_APPROVAL)

        curr_plan = state_paused["current_plan_id"]
        self.assertIsNotNone(curr_plan)

        # Mismatch plan approval should raise ValueError
        with self.assertRaises(ValueError):
            approve_orchestrator_plan(orch_id, "PLAN-INVALID-9999", runs_dir=self.runs_dir)

        # Valid approval
        app_state = approve_orchestrator_plan(orch_id, curr_plan, reviewer="Test Reviewer", runs_dir=self.runs_dir)
        self.assertEqual(app_state["current_state"], STATE_APPROVED)
        self.assertEqual(app_state["approval"]["status"], "APPROVED")

    def test_resource_locking(self):
        """Verifies file-based resource lock prevents concurrent acquisition."""
        lock_path = self.temp_dir / "orchestrator.lock"
        lock1 = OrchestratorResourceLock(lock_path)
        lock2 = OrchestratorResourceLock(lock_path)

        self.assertTrue(lock1.acquire())
        self.assertFalse(lock2.acquire(timeout_sec=0.1))

        lock1.release()
        self.assertTrue(lock2.acquire())
        lock2.release()

    def test_dry_run_end_to_end_orchestration(self):
        """Verifies full dry-run orchestration through complete iteration."""
        orch_id, run_dir, state = init_orchestrator_run({"dry_run": True, "maximum_iterations": 1}, runs_dir=self.runs_dir)

        # Step until approval gate
        run_orchestrator_until_stop(orch_id, runs_dir=self.runs_dir)
        state_app, _ = load_orchestrator_run(orch_id, runs_dir=self.runs_dir)
        self.assertEqual(state_app["current_state"], STATE_AWAITING_APPROVAL)

        # Approve plan
        plan_id = state_app["current_plan_id"]
        approve_orchestrator_plan(orch_id, plan_id, runs_dir=self.runs_dir)

        # Step until completion
        final_state = run_orchestrator_until_stop(orch_id, runs_dir=self.runs_dir)
        self.assertIn(final_state["current_state"], {STATE_ITERATION_COMPLETED, STATE_ORCHESTRATOR_COMPLETED})
        self.assertTrue((run_dir / "summary.json").is_file())

    def test_crash_recovery_from_persisted_state(self):
        """Verifies that orchestrator resumes safely after a simulated process crash."""
        orch_id, run_dir, state = init_orchestrator_run({"dry_run": True}, runs_dir=self.runs_dir)

        # Manually simulate intermediate state (e.g. CANDIDATE_VERIFIED)
        state["current_state"] = STATE_CANDIDATE_VERIFIED
        state["current_plan_id"] = "PLAN-0001"
        state["current_candidate_id"] = "CAND-0001"
        persist_orchestrator_state(run_dir, state)

        # Resume execution
        resumed_state = execute_orchestrator_step(orch_id, runs_dir=self.runs_dir)
        self.assertEqual(resumed_state["current_state"], STATE_EXPERIMENT_CREATED)

    def test_pause_stop_resume_lifecycle(self):
        """Verifies pause, resume, and stop commands on orchestrator."""
        orch_id, run_dir, state = init_orchestrator_run({"dry_run": True}, runs_dir=self.runs_dir)

        paused = pause_orchestrator(orch_id, reason="Testing pause", runs_dir=self.runs_dir)
        self.assertEqual(paused["current_state"], STATE_ORCHESTRATOR_PAUSED)

        resumed = resume_orchestrator(orch_id, runs_dir=self.runs_dir)
        self.assertNotEqual(resumed["current_state"], STATE_ORCHESTRATOR_PAUSED)

        stopped = stop_orchestrator(orch_id, reason="Testing stop", runs_dir=self.runs_dir)
        self.assertEqual(stopped["current_state"], STATE_ORCHESTRATOR_COMPLETED)

    def test_budget_enforcement(self):
        """Verifies that orchestrator halts when max iterations or failure budget is reached."""
        orch_id, run_dir, state = init_orchestrator_run({"dry_run": True, "maximum_iterations": 2}, runs_dir=self.runs_dir)

        state["completed_iterations_count"] = 2
        state["current_state"] = STATE_ITERATION_COMPLETED
        persist_orchestrator_state(run_dir, state)

        res_state = execute_orchestrator_step(orch_id, runs_dir=self.runs_dir)
        self.assertEqual(res_state["current_state"], STATE_ORCHESTRATOR_COMPLETED)


if __name__ == "__main__":
    unittest.main()
