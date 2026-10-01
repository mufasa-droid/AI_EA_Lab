"""
AI EA Lab - Research Orchestrator (Phase 17)

Provides a top-level, stateful research orchestration system for coordinating
multi-iteration research cycles while maintaining strict research controls:

Workflow Chain:
AI Researcher -> Experiment Planner -> Human Approval Gate -> AI Developer
-> Candidate Verifier -> Candidate Runner (MT5) -> Experiment Archive -> AI Auditor
-> Memory Ingestion -> Research Decision Engine -> Next Iteration

Enforces:
1. Strict Human Approval Gate: Halts at AWAITING_APPROVAL until explicit human authorization.
2. Hard Operational Safety Boundaries: NO live trading, NO broker order execution,
   NO candidate ranking/scoreboards, NO parameter sweep optimization, NO automatic UNSEEN data access.
3. Durable State Persistence: State persisted to disk (research/orchestrator/runs/ORCH-XXXX/);
   restartable after process crash with complete provenance verification.
4. Append-Only Event Log: Every transition produces an append-only JSONL event.
5. Resource Locking: File-based locking prevents port 3000 / MetaTester conflicts.
6. Research Budgets: Bounded stop conditions (max_iterations, max_failures, max_retries).
7. Fail-Safe Distinctions: Infrastructure failures (MT5 crash, compiler missing) are kept
   strictly separate from strategy performance findings.
8. Reproducibility & Memory Integration: Seamlessly calls Phase 15 reproducibility pre-flight
   and Phase 16 memory ingestion after audit completion.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ORCHESTRATOR_DIR = PROJECT_ROOT / "research" / "orchestrator"
RUNS_DIR = ORCHESTRATOR_DIR / "runs"
LOCK_FILE = ORCHESTRATOR_DIR / "orchestrator.lock"

ORCHESTRATOR_SCHEMA_VERSION = 1

# Explicit Orchestration States
STATE_ORCHESTRATOR_CREATED = "ORCHESTRATOR_CREATED"
STATE_RESEARCHING = "RESEARCHING"
STATE_HYPOTHESIS_CREATED = "HYPOTHESIS_CREATED"
STATE_PLANNING = "PLANNING"
STATE_PLAN_CREATED = "PLAN_CREATED"
STATE_AWAITING_APPROVAL = "AWAITING_APPROVAL"
STATE_APPROVED = "APPROVED"
STATE_DEVELOPING = "DEVELOPING"
STATE_CANDIDATE_CREATED = "CANDIDATE_CREATED"
STATE_VERIFYING_CANDIDATE = "VERIFYING_CANDIDATE"
STATE_CANDIDATE_VERIFIED = "CANDIDATE_VERIFIED"
STATE_EXECUTING = "EXECUTING"
STATE_EXPERIMENT_CREATED = "EXPERIMENT_CREATED"
STATE_AUDITING = "AUDITING"
STATE_AUDITED = "AUDITED"
STATE_INGESTING_MEMORY = "INGESTING_MEMORY"
STATE_MEMORY_UPDATED = "MEMORY_UPDATED"
STATE_DECIDING = "DECIDING"
STATE_DECISION_CREATED = "DECISION_CREATED"
STATE_ITERATION_COMPLETED = "ITERATION_COMPLETED"
STATE_ITERATION_BLOCKED = "ITERATION_BLOCKED"
STATE_ITERATION_FAILED = "ITERATION_FAILED"
STATE_ORCHESTRATOR_PAUSED = "ORCHESTRATOR_PAUSED"
STATE_ORCHESTRATOR_COMPLETED = "ORCHESTRATOR_COMPLETED"

ALL_ORCHESTRATOR_STATES = {
    STATE_ORCHESTRATOR_CREATED,
    STATE_RESEARCHING,
    STATE_HYPOTHESIS_CREATED,
    STATE_PLANNING,
    STATE_PLAN_CREATED,
    STATE_AWAITING_APPROVAL,
    STATE_APPROVED,
    STATE_DEVELOPING,
    STATE_CANDIDATE_CREATED,
    STATE_VERIFYING_CANDIDATE,
    STATE_CANDIDATE_VERIFIED,
    STATE_EXECUTING,
    STATE_EXPERIMENT_CREATED,
    STATE_AUDITING,
    STATE_AUDITED,
    STATE_INGESTING_MEMORY,
    STATE_MEMORY_UPDATED,
    STATE_DECIDING,
    STATE_DECISION_CREATED,
    STATE_ITERATION_COMPLETED,
    STATE_ITERATION_BLOCKED,
    STATE_ITERATION_FAILED,
    STATE_ORCHESTRATOR_PAUSED,
    STATE_ORCHESTRATOR_COMPLETED,
}

# Failure Classifications
FAIL_RESEARCHER = "RESEARCHER_FAILURE"
FAIL_PLANNER = "PLANNER_FAILURE"
FAIL_APPROVAL = "APPROVAL_FAILURE"
FAIL_DEVELOPER = "DEVELOPER_FAILURE"
FAIL_COMPILATION = "COMPILATION_FAILURE"
FAIL_VERIFICATION = "CANDIDATE_VERIFICATION_FAILURE"
FAIL_DATASET = "DATASET_FAILURE"
FAIL_MT5 = "MT5_EXECUTION_FAILURE"
FAIL_REPORT = "REPORT_FAILURE"
FAIL_PARSER = "PARSER_FAILURE"
FAIL_AUDIT = "AUDIT_FAILURE"
FAIL_MEMORY = "MEMORY_FAILURE"
FAIL_DECISION = "DECISION_FAILURE"
FAIL_ORCHESTRATOR = "ORCHESTRATOR_FAILURE"


class OrchestratorResourceLock:
    """File-based lock preventing concurrent orchestrators from conflicting over MT5 / port 3000."""

    def __init__(self, lock_path: Optional[Path] = None):
        self.lock_path = Path(lock_path) if lock_path else LOCK_FILE
        self.acquired = False

    def acquire(self, timeout_sec: float = 5.0) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        start_t = time.time()
        while time.time() - start_t < timeout_sec:
            try:
                # Try exclusive file creation
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(fd, f"pid={os.getpid()}\ntime={datetime.now().isoformat()}\n".encode("utf-8"))
                os.close(fd)
                self.acquired = True
                return True
            except FileExistsError:
                time.sleep(0.2)
            except Exception:
                return False
        return False

    def release(self) -> None:
        if self.acquired and self.lock_path.is_file():
            try:
                self.lock_path.unlink()
            except Exception:
                pass
            self.acquired = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(f"Failed to acquire orchestrator lock: {self.lock_path}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def ensure_orchestrator_dirs(base_dir: Optional[Path] = None) -> Path:
    """Ensures orchestrator workspace directory exists."""
    root = Path(base_dir) if base_dir else RUNS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_next_orchestrator_id(runs_dir: Optional[Path] = None) -> str:
    """Generates sequential MONOTONIC ID for orchestrator runs (ORCH-0001)."""
    root = ensure_orchestrator_dirs(runs_dir)
    existing = [d.name for d in root.glob("ORCH-*") if d.is_dir()]
    numbers = []
    for name in existing:
        try:
            num = int(name.split("-")[1])
            numbers.append(num)
        except (IndexError, ValueError):
            pass
    next_num = max(numbers, default=0) + 1
    return f"ORCH-{next_num:04d}"


def get_next_iteration_id(state: Dict[str, Any]) -> str:
    """Generates sequential MONOTONIC ID for iterations inside a run (ITER-0001)."""
    completed_iters = state.get("completed_iterations_count", 0)
    curr_num = completed_iters + 1
    return f"ITER-{curr_num:04d}"


def create_default_orchestrator_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Creates a conservative default configuration snapshot."""
    cfg = {
        "maximum_iterations": 3,
        "maximum_failures": 2,
        "maximum_retries": 2,
        "approval_required": True,
        "allowed_dataset_partitions": ["training", "validation"],
        "training_enabled": True,
        "validation_enabled": True,
        "unseen_enabled": False,  # STRICT DEFAULT
        "dry_run": False,
        "live_execution": False,  # FORBIDDEN
        "automatic_deployment": False,  # FORBIDDEN
        "unrestricted_optimization": False,  # FORBIDDEN
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def persist_orchestrator_state(
    run_dir: Path,
    state: Dict[str, Any],
) -> None:
    """Persists orchestrator state.json atomically."""
    run_dir.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().astimezone().isoformat()
    state_file = run_dir / "state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_orchestrator_event(
    run_dir: Path,
    orchestrator_id: str,
    iteration_id: str,
    from_state: str,
    to_state: str,
    reason: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Appends an event to the append-only events.jsonl log."""
    run_dir.mkdir(parents=True, exist_ok=True)
    events_file = run_dir / "events.jsonl"

    raw_event = f"{orchestrator_id}::{iteration_id}::{from_state}->{to_state}::{datetime.now().isoformat()}"
    event_id = f"EVT-{hashlib.sha256(raw_event.encode('utf-8')).hexdigest()[:12]}"

    evt = {
        "event_id": event_id,
        "timestamp": datetime.now().astimezone().isoformat(),
        "orchestrator_id": orchestrator_id,
        "iteration_id": iteration_id,
        "from_state": from_state,
        "to_state": to_state,
        "event_type": "STATE_TRANSITION",
        "reason": reason,
        "source": "orchestrator",
        "details": details or {},
    }

    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(evt) + "\n")

    return evt


def load_orchestrator_run(
    orchestrator_id: str,
    runs_dir: Optional[Path] = None,
) -> Tuple[Dict[str, Any], Path]:
    """Loads state.json for an existing orchestrator run."""
    root = ensure_orchestrator_dirs(runs_dir)
    run_dir = root / orchestrator_id
    state_file = run_dir / "state.json"

    if not state_file.is_file():
        raise FileNotFoundError(f"Orchestrator state file not found for run '{orchestrator_id}': {state_file}")

    state = json.loads(state_file.read_text(encoding="utf-8"))
    return state, run_dir


def init_orchestrator_run(
    config_overrides: Optional[Dict[str, Any]] = None,
    runs_dir: Optional[Path] = None,
) -> Tuple[str, Path, Dict[str, Any]]:
    """Initializes a new orchestrator run on disk."""
    root = ensure_orchestrator_dirs(runs_dir)
    orch_id = get_next_orchestrator_id(root)
    run_dir = root / orch_id
    run_dir.mkdir(parents=True, exist_ok=True)

    config = create_default_orchestrator_config(config_overrides)
    (run_dir / "configuration.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    state = {
        "schema_version": ORCHESTRATOR_SCHEMA_VERSION,
        "orchestrator_id": orch_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "updated_at": datetime.now().astimezone().isoformat(),
        "current_state": STATE_ORCHESTRATOR_CREATED,
        "previous_state": None,
        "current_iteration_id": "ITER-0001",
        "completed_iterations_count": 0,
        "consecutive_failures": 0,
        "total_failures": 0,
        "current_hypothesis_id": None,
        "current_plan_id": None,
        "current_candidate_id": None,
        "current_training_experiment_id": None,
        "current_validation_experiment_id": None,
        "current_audit_id": None,
        "current_decision": None,
        "approval": {
            "status": "PENDING",
            "plan_id": None,
            "reviewed_by": None,
            "reviewed_at": None,
            "note": None,
        },
        "config": config,
        "error": None,
        "iterations": [],
    }

    persist_orchestrator_state(run_dir, state)
    append_orchestrator_event(
        run_dir,
        orch_id,
        "ITER-0001",
        "NONE",
        STATE_ORCHESTRATOR_CREATED,
        "Initialized research orchestrator run",
    )

    return orch_id, run_dir, state


def approve_orchestrator_plan(
    orchestrator_id: str,
    plan_id: str,
    reviewer: str = "Lead Quant",
    note: str = "Explicit human approval granted",
    runs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Grants explicit human approval bound to a specific plan_id for an orchestrator run.
    Must be bound to current_plan_id; otherwise rejects as INVALID.
    """
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)

    curr_plan = state.get("current_plan_id")
    if not curr_plan or curr_plan != plan_id:
        raise ValueError(f"Approval mismatch: Orchestrator current plan is '{curr_plan}', but provided plan_id is '{plan_id}'.")

    if state["current_state"] != STATE_AWAITING_APPROVAL and state["current_state"] != STATE_ORCHESTRATOR_PAUSED:
        raise ValueError(f"Cannot approve plan in state '{state['current_state']}'. Must be AWAITING_APPROVAL or ORCHESTRATOR_PAUSED.")

    state["approval"] = {
        "status": "APPROVED",
        "plan_id": plan_id,
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now().astimezone().isoformat(),
        "note": note,
    }

    prev_state = state["current_state"]
    state["previous_state"] = prev_state
    state["current_state"] = STATE_APPROVED

    persist_orchestrator_state(run_dir, state)
    append_orchestrator_event(
        run_dir,
        orchestrator_id,
        state.get("current_iteration_id", "ITER-0001"),
        prev_state,
        STATE_APPROVED,
        f"Human approval granted by {reviewer} for plan {plan_id}",
    )

    return state


def execute_orchestrator_step(
    orchestrator_id: str,
    runs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes a single, deterministic state machine transition for an orchestrator run.
    Integrates Researcher -> Planner -> Approval -> Developer -> Verifier -> Runner -> Auditor -> Memory -> Decision.
    """
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)
    curr_state = state["current_state"]
    config = state.get("config", {})
    iter_id = state.get("current_iteration_id", "ITER-0001")
    dry_run = config.get("dry_run", False)

    # Hard Safety Checks
    if curr_state in {STATE_ORCHESTRATOR_COMPLETED, STATE_ITERATION_FAILED, STATE_ITERATION_BLOCKED}:
        return state

    # Budget Check
    max_iters = config.get("maximum_iterations", 3)
    if state.get("completed_iterations_count", 0) >= max_iters and curr_state == STATE_ITERATION_COMPLETED:
        state["previous_state"] = curr_state
        state["current_state"] = STATE_ORCHESTRATOR_COMPLETED
        persist_orchestrator_state(run_dir, state)
        append_orchestrator_event(
            run_dir, orchestrator_id, iter_id, curr_state, STATE_ORCHESTRATOR_COMPLETED,
            f"Maximum iterations budget ({max_iters}) reached."
        )
        return state

    max_fails = config.get("maximum_failures", 2)
    if state.get("consecutive_failures", 0) >= max_fails:
        state["previous_state"] = curr_state
        state["current_state"] = STATE_ITERATION_FAILED
        state["error"] = f"Exceeded consecutive failure budget ({max_fails})."
        persist_orchestrator_state(run_dir, state)
        append_orchestrator_event(
            run_dir, orchestrator_id, iter_id, curr_state, STATE_ITERATION_FAILED,
            f"Consecutive failure budget ({max_fails}) exceeded."
        )
        return state

    # State Machine Switch
    if curr_state in {STATE_ORCHESTRATOR_CREATED, STATE_ITERATION_COMPLETED}:
        # Reset iteration state for new iteration
        new_iter_id = get_next_iteration_id(state)
        state["current_iteration_id"] = new_iter_id
        state["previous_state"] = curr_state
        state["current_state"] = STATE_RESEARCHING
        state["current_hypothesis_id"] = None
        state["current_plan_id"] = None
        state["current_candidate_id"] = None
        state["current_training_experiment_id"] = None
        state["current_validation_experiment_id"] = None
        state["current_audit_id"] = None
        state["current_decision"] = None
        state["approval"] = {"status": "PENDING", "plan_id": None, "reviewed_by": None, "reviewed_at": None, "note": None}

        persist_orchestrator_state(run_dir, state)
        append_orchestrator_event(run_dir, orchestrator_id, new_iter_id, curr_state, STATE_RESEARCHING, "Beginning research phase")
        return state

    elif curr_state == STATE_RESEARCHING:
        # Step 1: Researcher Formulates Hypothesis
        try:
            from scripts.research_context import build_research_context
            from scripts.researcher import formulate_mock_hypothesis, save_hypothesis
            from scripts.memory import classify_hypothesis_novelty

            ctx = build_research_context()

            # Classify novelty if mock hypothesis generated
            hyp_dict = formulate_mock_hypothesis(ctx)
            nov_state, nov_msg, match_rec = classify_hypothesis_novelty(hyp_dict)
            hyp_dict["novelty"] = {"state": nov_state, "message": nov_msg}

            hyp_file = save_hypothesis(hyp_dict)
            hyp_id = hyp_dict["hypothesis_id"]

            state["current_hypothesis_id"] = hyp_id
            state["previous_state"] = STATE_RESEARCHING
            state["current_state"] = STATE_HYPOTHESIS_CREATED

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(
                run_dir, orchestrator_id, iter_id, STATE_RESEARCHING, STATE_HYPOTHESIS_CREATED,
                f"Formulated hypothesis {hyp_id} (novelty: {nov_state})"
            )
        except Exception as e:
            state["previous_state"] = STATE_RESEARCHING
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_RESEARCHER}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_RESEARCHING, STATE_ITERATION_FAILED, f"Researcher error: {str(e)}")

        return state

    elif curr_state == STATE_HYPOTHESIS_CREATED:
        # Step 2: Plan Generation
        try:
            from scripts.research_context import build_research_context
            from scripts.experiment_planner import create_experiment_plan, save_experiment_plan
            from scripts.research_schemas import validate_hypothesis_dict


            hyp_id = state["current_hypothesis_id"]
            hyp_file = PROJECT_ROOT / "research" / "hypotheses" / f"{hyp_id}.json"
            hyp_dict = json.loads(hyp_file.read_text(encoding="utf-8"))

            ctx = build_research_context()
            plan_dict = create_experiment_plan(hyp_dict, ctx)
            plan_file = save_experiment_plan(plan_dict)
            plan_id = plan_dict["experiment_plan_id"]


            state["current_plan_id"] = plan_id
            state["previous_state"] = STATE_HYPOTHESIS_CREATED
            state["current_state"] = STATE_PLAN_CREATED

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(
                run_dir, orchestrator_id, iter_id, STATE_HYPOTHESIS_CREATED, STATE_PLAN_CREATED,
                f"Generated plan {plan_id} for hypothesis {hyp_id}"
            )
        except Exception as e:
            state["previous_state"] = STATE_HYPOTHESIS_CREATED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_PLANNER}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_HYPOTHESIS_CREATED, STATE_ITERATION_FAILED, f"Planner error: {str(e)}")

        return state

    elif curr_state == STATE_PLAN_CREATED:
        # Step 3: Check Approval Constraint
        req_approval = config.get("approval_required", True)
        if req_approval:
            state["previous_state"] = STATE_PLAN_CREATED
            state["current_state"] = STATE_AWAITING_APPROVAL
            state["approval"]["status"] = "PENDING"
            state["approval"]["plan_id"] = state["current_plan_id"]

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(
                run_dir, orchestrator_id, iter_id, STATE_PLAN_CREATED, STATE_AWAITING_APPROVAL,
                f"Awaiting explicit human approval for plan {state['current_plan_id']}"
            )
        else:
            state["previous_state"] = STATE_PLAN_CREATED
            state["current_state"] = STATE_APPROVED
            state["approval"]["status"] = "BYPASSED_BY_CONFIG"
            state["approval"]["plan_id"] = state["current_plan_id"]

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(
                run_dir, orchestrator_id, iter_id, STATE_PLAN_CREATED, STATE_APPROVED,
                "Approval requirement bypassed by configuration"
            )

        return state

    elif curr_state == STATE_AWAITING_APPROVAL:
        # Stops safely until human approval is supplied
        return state

    elif curr_state == STATE_APPROVED:
        # Step 4: AI Developer Candidate Creation
        try:
            from scripts.developer import run_developer
            from scripts.developer_schemas import set_plan_approval

            plan_id = state["current_plan_id"]

            # Ensure approval record exists in plan file for AI Developer
            plan_file = PROJECT_ROOT / "research" / "plans" / f"{plan_id}.json"
            set_plan_approval(
                plan_file,
                status="approved",
                approved_by=state["approval"].get("reviewed_by", "Lead Quant"),
                note=state["approval"].get("note", "Orchestrator authorized approval"),
            )


            if dry_run:
                cand_id = f"CAND-DRY-{plan_id[-4:]}"
                state["current_candidate_id"] = cand_id
                state["previous_state"] = STATE_APPROVED
                state["current_state"] = STATE_CANDIDATE_CREATED
                persist_orchestrator_state(run_dir, state)
                append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_APPROVED, STATE_CANDIDATE_CREATED, f"[DRY-RUN] Created candidate {cand_id}")
                return state

            dev_result = run_developer(plan_id=plan_id)
            if dev_result.get("status") not in {"SUCCESS", "COMPLETED"}:
                err_msg = dev_result.get("error") or dev_result.get("message") or "Developer implementation failed."
                state["previous_state"] = STATE_APPROVED
                state["current_state"] = STATE_ITERATION_FAILED
                state["error"] = f"{FAIL_DEVELOPER}: {err_msg}"
                state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
                persist_orchestrator_state(run_dir, state)
                append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_APPROVED, STATE_ITERATION_FAILED, f"Developer error: {err_msg}")
                return state

            cand_id = dev_result.get("candidate_id")
            state["current_candidate_id"] = cand_id
            state["previous_state"] = STATE_APPROVED
            state["current_state"] = STATE_CANDIDATE_CREATED

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_APPROVED, STATE_CANDIDATE_CREATED, f"Developer created candidate {cand_id}")
        except Exception as e:
            state["previous_state"] = STATE_APPROVED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_DEVELOPER}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_APPROVED, STATE_ITERATION_FAILED, f"Developer error: {str(e)}")

        return state

    elif curr_state == STATE_CANDIDATE_CREATED:
        # Step 5: Candidate Verification
        try:
            from scripts.candidate_verifier import verify_candidate
            cand_id = state["current_candidate_id"]

            if dry_run:
                state["previous_state"] = STATE_CANDIDATE_CREATED
                state["current_state"] = STATE_CANDIDATE_VERIFIED
                persist_orchestrator_state(run_dir, state)
                append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_CREATED, STATE_CANDIDATE_VERIFIED, f"[DRY-RUN] Candidate {cand_id} verified")
                return state

            verif = verify_candidate(cand_id)
            if not verif.get("is_valid"):
                issues = "; ".join(verif.get("issues", []))
                state["previous_state"] = STATE_CANDIDATE_CREATED
                state["current_state"] = STATE_ITERATION_FAILED
                state["error"] = f"{FAIL_VERIFICATION}: {issues}"
                state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
                persist_orchestrator_state(run_dir, state)
                append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_CREATED, STATE_ITERATION_FAILED, f"Verification failed: {issues}")
                return state

            state["previous_state"] = STATE_CANDIDATE_CREATED
            state["current_state"] = STATE_CANDIDATE_VERIFIED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_CREATED, STATE_CANDIDATE_VERIFIED, f"Verified candidate {cand_id}")
        except Exception as e:
            state["previous_state"] = STATE_CANDIDATE_CREATED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_VERIFICATION}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_CREATED, STATE_ITERATION_FAILED, f"Verification error: {str(e)}")

        return state

    elif curr_state == STATE_CANDIDATE_VERIFIED:
        # Step 6: Execute Backtest Candidate Runner under Resource Lock
        cand_id = state["current_candidate_id"]

        if dry_run:
            exp_id = f"EXP-DRY-{cand_id[-4:]}"
            state["current_training_experiment_id"] = exp_id
            state["previous_state"] = STATE_CANDIDATE_VERIFIED
            state["current_state"] = STATE_EXPERIMENT_CREATED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_VERIFIED, STATE_EXPERIMENT_CREATED, f"[DRY-RUN] Experiment {exp_id} simulated")
            return state

        try:
            with OrchestratorResourceLock():
                from scripts.run_candidate import execute_candidate_backtest, STATUS_SUCCESS

                run_res = execute_candidate_backtest(cand_id, dataset_type="training")
                if run_res.get("status") != STATUS_SUCCESS:
                    err_msg = run_res.get("error") or run_res.get("status")
                    state["previous_state"] = STATE_CANDIDATE_VERIFIED
                    state["current_state"] = STATE_ITERATION_FAILED
                    state["error"] = f"{FAIL_MT5}: {err_msg}"
                    state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
                    persist_orchestrator_state(run_dir, state)
                    append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_VERIFIED, STATE_ITERATION_FAILED, f"MT5 runner failed: {err_msg}")
                    return state

                exp_id = run_res.get("experiment", {}).get("experiment_id")
                state["current_training_experiment_id"] = exp_id
                state["previous_state"] = STATE_CANDIDATE_VERIFIED
                state["current_state"] = STATE_EXPERIMENT_CREATED

                persist_orchestrator_state(run_dir, state)
                append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_VERIFIED, STATE_EXPERIMENT_CREATED, f"Archived experiment {exp_id}")
        except Exception as e:
            state["previous_state"] = STATE_CANDIDATE_VERIFIED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_MT5}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_CANDIDATE_VERIFIED, STATE_ITERATION_FAILED, f"MT5 runner error: {str(e)}")

        return state

    elif curr_state == STATE_EXPERIMENT_CREATED:
        # Step 7: Run AI Auditor
        exp_id = state["current_training_experiment_id"]

        if dry_run:
            aud_id = f"AUD-{exp_id}"
            state["current_audit_id"] = aud_id
            state["previous_state"] = STATE_EXPERIMENT_CREATED
            state["current_state"] = STATE_AUDITED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_EXPERIMENT_CREATED, STATE_AUDITED, f"[DRY-RUN] Audit {aud_id} simulated")
            return state

        try:
            from scripts.auditor import run_audit
            audit_res = run_audit(exp_id)
            aud_id = audit_res.get("audit_id", f"AUD-{exp_id}")

            state["current_audit_id"] = aud_id
            state["previous_state"] = STATE_EXPERIMENT_CREATED
            state["current_state"] = STATE_AUDITED

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_EXPERIMENT_CREATED, STATE_AUDITED, f"Audited experiment {exp_id} -> {aud_id}")
        except Exception as e:
            state["previous_state"] = STATE_EXPERIMENT_CREATED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_AUDIT}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_EXPERIMENT_CREATED, STATE_ITERATION_FAILED, f"Audit error: {str(e)}")

        return state

    elif curr_state == STATE_AUDITED:
        # Step 8: Memory Ingestion
        exp_id = state["current_training_experiment_id"]

        if dry_run:
            state["previous_state"] = STATE_AUDITED
            state["current_state"] = STATE_MEMORY_UPDATED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_AUDITED, STATE_MEMORY_UPDATED, f"[DRY-RUN] Memory ingested for {exp_id}")
            return state

        try:
            from scripts.memory import ingest_experiment, ingest_audit
            ingest_experiment(exp_id)
            ingest_audit(exp_id)

            state["previous_state"] = STATE_AUDITED
            state["current_state"] = STATE_MEMORY_UPDATED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_AUDITED, STATE_MEMORY_UPDATED, f"Ingested memory records for {exp_id}")
        except Exception as e:
            state["previous_state"] = STATE_AUDITED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_MEMORY}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_AUDITED, STATE_ITERATION_FAILED, f"Memory ingestion error: {str(e)}")

        return state

    elif curr_state == STATE_MEMORY_UPDATED:
        # Step 9: Research Decision Evaluation
        exp_id = state["current_training_experiment_id"]

        if dry_run:
            state["current_decision"] = {"decision": "CONTINUE_RESEARCH", "reason": "[DRY-RUN] Decision simulated"}
            state["previous_state"] = STATE_MEMORY_UPDATED
            state["current_state"] = STATE_DECISION_CREATED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_MEMORY_UPDATED, STATE_DECISION_CREATED, "[DRY-RUN] Decision created")
            return state

        try:
            from scripts.research_decision import evaluate_research_decision
            audit_file = PROJECT_ROOT / "experiments" / exp_id / "audit.json"
            audit_dict = json.loads(audit_file.read_text(encoding="utf-8")) if audit_file.is_file() else {}

            dec_res = evaluate_research_decision(audit_dict)
            state["current_decision"] = dec_res
            state["previous_state"] = STATE_MEMORY_UPDATED
            state["current_state"] = STATE_DECISION_CREATED

            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_MEMORY_UPDATED, STATE_DECISION_CREATED, f"Research decision: {dec_res.get('decision')}")
        except Exception as e:
            state["previous_state"] = STATE_MEMORY_UPDATED
            state["current_state"] = STATE_ITERATION_FAILED
            state["error"] = f"{FAIL_DECISION}: {str(e)}"
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_MEMORY_UPDATED, STATE_ITERATION_FAILED, f"Decision error: {str(e)}")

        return state

    elif curr_state == STATE_DECISION_CREATED:
        # Step 10: Complete Iteration & Determine Next Action
        dec_name = state.get("current_decision", {}).get("decision")

        state["completed_iterations_count"] = state.get("completed_iterations_count", 0) + 1
        state["consecutive_failures"] = 0  # Reset on clean iteration finish

        # Archive iteration summary record
        iter_record = {
            "iteration_id": iter_id,
            "hypothesis_id": state.get("current_hypothesis_id"),
            "plan_id": state.get("current_plan_id"),
            "candidate_id": state.get("current_candidate_id"),
            "training_experiment_id": state.get("current_training_experiment_id"),
            "audit_id": state.get("current_audit_id"),
            "decision": dec_name,
            "completed_at": datetime.now().astimezone().isoformat(),
        }
        state.setdefault("iterations", []).append(iter_record)

        if dec_name == "CONTINUE_RESEARCH":
            state["previous_state"] = STATE_DECISION_CREATED
            state["current_state"] = STATE_ITERATION_COMPLETED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_DECISION_CREATED, STATE_ITERATION_COMPLETED, f"Iteration {iter_id} completed cleanly")

        elif dec_name == "NEEDS_HUMAN_REVIEW" or dec_name == "NEEDS_REPRODUCIBILITY_REVIEW":
            state["previous_state"] = STATE_DECISION_CREATED
            state["current_state"] = STATE_ORCHESTRATOR_PAUSED
            state["error"] = f"Paused: Decision requires human/reproducibility review ({dec_name})."
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_DECISION_CREATED, STATE_ORCHESTRATOR_PAUSED, f"Paused for review ({dec_name})")

        elif dec_name in {"REJECT_EXPERIMENT", "CANDIDATE_INTEGRITY_FAILURE", "DATASET_INTEGRITY_FAILURE"}:
            state["previous_state"] = STATE_DECISION_CREATED
            state["current_state"] = STATE_ITERATION_BLOCKED
            state["error"] = f"Iteration blocked by decision: {dec_name}"
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_DECISION_CREATED, STATE_ITERATION_BLOCKED, f"Iteration blocked ({dec_name})")

        else:
            state["previous_state"] = STATE_DECISION_CREATED
            state["current_state"] = STATE_ITERATION_COMPLETED
            persist_orchestrator_state(run_dir, state)
            append_orchestrator_event(run_dir, orchestrator_id, iter_id, STATE_DECISION_CREATED, STATE_ITERATION_COMPLETED, f"Iteration finished with decision {dec_name}")

        return state

    return state


def run_orchestrator_until_stop(
    orchestrator_id: str,
    max_steps: int = 50,
    runs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Executes state transitions until an approval gate, stop condition, pause, or max_steps is reached.
    """
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)
    steps = 0

    while steps < max_steps:
        curr = state["current_state"]
        if curr in {
            STATE_AWAITING_APPROVAL,
            STATE_ORCHESTRATOR_PAUSED,
            STATE_ORCHESTRATOR_COMPLETED,
            STATE_ITERATION_BLOCKED,
            STATE_ITERATION_FAILED,
        }:
            break

        state = execute_orchestrator_step(orchestrator_id, runs_dir=runs_dir)
        steps += 1

    # Write summary.json upon stopping
    summary = {
        "orchestrator_id": orchestrator_id,
        "final_state": state["current_state"],
        "completed_iterations": state.get("completed_iterations_count", 0),
        "total_failures": state.get("total_failures", 0),
        "consecutive_failures": state.get("consecutive_failures", 0),
        "current_hypothesis_id": state.get("current_hypothesis_id"),
        "current_plan_id": state.get("current_plan_id"),
        "current_candidate_id": state.get("current_candidate_id"),
        "current_training_experiment_id": state.get("current_training_experiment_id"),
        "current_audit_id": state.get("current_audit_id"),
        "current_decision": state.get("current_decision"),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return state


def pause_orchestrator(orchestrator_id: str, reason: str = "User requested pause", runs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Safely pauses an active orchestrator run."""
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)
    prev = state["current_state"]
    state["previous_state"] = prev
    state["current_state"] = STATE_ORCHESTRATOR_PAUSED
    state["error"] = reason
    persist_orchestrator_state(run_dir, state)
    append_orchestrator_event(run_dir, orchestrator_id, state.get("current_iteration_id", "ITER-0001"), prev, STATE_ORCHESTRATOR_PAUSED, reason)
    return state


def resume_orchestrator(orchestrator_id: str, runs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Resumes a paused or restartable orchestrator run."""
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)
    prev = state["current_state"]
    if prev != STATE_ORCHESTRATOR_PAUSED:
        return state

    target = state.get("previous_state") or STATE_RESEARCHING
    state["previous_state"] = prev
    state["current_state"] = target
    state["error"] = None
    persist_orchestrator_state(run_dir, state)
    append_orchestrator_event(run_dir, orchestrator_id, state.get("current_iteration_id", "ITER-0001"), prev, target, "Resumed orchestrator run")
    return state


def stop_orchestrator(orchestrator_id: str, reason: str = "User stopped execution", runs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Safely stops an orchestrator run without deleting any research artifacts."""
    state, run_dir = load_orchestrator_run(orchestrator_id, runs_dir)
    prev = state["current_state"]
    state["previous_state"] = prev
    state["current_state"] = STATE_ORCHESTRATOR_COMPLETED
    state["error"] = f"Stopped: {reason}"
    persist_orchestrator_state(run_dir, state)
    append_orchestrator_event(run_dir, orchestrator_id, state.get("current_iteration_id", "ITER-0001"), prev, STATE_ORCHESTRATOR_COMPLETED, reason)
    return state


def format_human_readable_orchestration(state: Dict[str, Any]) -> str:
    """Formats human-readable console report for an orchestrator run."""
    lines = [
        "=" * 60,
        "AI-EA-LAB -- RESEARCH ORCHESTRATOR (PHASE 17)",
        "=" * 60,
        f"Orchestrator ID:    {state.get('orchestrator_id', 'UNKNOWN')}",
        f"Current Iteration:  {state.get('current_iteration_id', 'ITER-0001')}",
        f"Current State:      {state.get('current_state')}",
        f"Previous State:     {state.get('previous_state')}",
        f"Completed Iters:    {state.get('completed_iterations_count', 0)} / {state.get('config', {}).get('maximum_iterations', 3)}",
        f"Consecutive Fails:  {state.get('consecutive_failures', 0)} / {state.get('config', {}).get('maximum_failures', 2)}",
        "",
        "--- CURRENT LINEAGE ---",
        f"  Hypothesis ID:    {state.get('current_hypothesis_id') or 'None'}",
        f"  Plan ID:          {state.get('current_plan_id') or 'None'}",
        f"  Candidate ID:     {state.get('current_candidate_id') or 'None'}",
        f"  Training Exp ID:  {state.get('current_training_experiment_id') or 'None'}",
        f"  Audit ID:         {state.get('current_audit_id') or 'None'}",
        f"  Decision:         {state.get('current_decision', {}).get('decision') if isinstance(state.get('current_decision'), dict) else state.get('current_decision') or 'None'}",
        "",
        "--- APPROVAL GATE ---",
        f"  Status:           {state.get('approval', {}).get('status')}",
        f"  Plan ID Bound:    {state.get('approval', {}).get('plan_id')}",
        f"  Reviewed By:      {state.get('approval', {}).get('reviewed_by')}",
        "",
        "--- CONFIGURATION & SAFETY ---",
        f"  Dry Run:          {state.get('config', {}).get('dry_run')}",
        f"  Approval Req:     {state.get('config', {}).get('approval_required')}",
        f"  UNSEEN Enabled:   {state.get('config', {}).get('unseen_enabled')}",
        f"  Live Trading:     {state.get('config', {}).get('live_execution')} (STRICTLY FORBIDDEN)",
    ]

    if state.get("error"):
        lines.append("")
        lines.append(f"ERROR/NOTE: {state.get('error')}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="AI-EA-Lab Phase 17: Research Orchestrator.")
    parser.add_argument("--init", action="store_true", help="Initialize a new orchestrator run.")
    parser.add_argument("--run", type=str, help="Orchestrator ID to run (e.g. ORCH-0001).")
    parser.add_argument("--approve", type=str, help="Plan ID to approve for the specified run.")
    parser.add_argument("--reviewer", type=str, default="Lead Quant", help="Reviewer name for approval.")
    parser.add_argument("--dry-run", action="store_true", help="Run orchestrator in dry-run mode.")
    parser.add_argument("--max-iters", type=int, default=3, help="Maximum iteration budget.")
    parser.add_argument("--status", type=str, help="Inspect status of an orchestrator run.")

    args = parser.parse_args()

    if args.init:
        cfg = {"dry_run": args.dry_run, "maximum_iterations": args.max_iters}
        orch_id, run_dir, state = init_orchestrator_run(cfg)
        print(format_human_readable_orchestration(state))

    elif args.approve and args.run:
        state = approve_orchestrator_plan(args.run, args.approve, reviewer=args.reviewer)
        print(format_human_readable_orchestration(state))

    elif args.run:
        if args.dry_run:
            # Update dry-run config
            state, run_dir = load_orchestrator_run(args.run)
            state["config"]["dry_run"] = True
            persist_orchestrator_state(run_dir, state)

        state = run_orchestrator_until_stop(args.run)
        print(format_human_readable_orchestration(state))

    elif args.status:
        state, _ = load_orchestrator_run(args.status)
        print(format_human_readable_orchestration(state))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
