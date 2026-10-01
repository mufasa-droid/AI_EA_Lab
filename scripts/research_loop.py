"""
AI EA Lab - Controlled Autonomous Research Loop Orchestrator (Phase 11)

The top-level research orchestration layer.
Connects:
AI Researcher -> Experiment Planner -> Human Approval Gate -> AI Developer
-> Candidate Verifier -> Candidate Runner (MT5) -> AI Auditor -> Research Decision Engine.

Enforces:
1. Strict Human Approval Gate (stops safely before candidate development).
2. Monotonic Iteration IDs (ITER-XXXX).
3. Explicit State Machine (CREATED -> RESEARCHING -> PLANNED -> AWAITING_APPROVAL
   -> APPROVED -> DEVELOPING -> CANDIDATE_READY -> BACKTESTING -> EXPERIMENT_CREATED
   -> AUDITING -> AUDITED -> DECIDED -> COMPLETED / FAILED / BLOCKED).
4. Provenance Chain (HYP -> PLAN -> CAND -> EXP -> AUD -> ITERATION DECISION).
5. Dataset Discipline (surfaces unconfigured vs configured periods).
6. Fail-Safe Behavior (stops on verification, compiler, tester, or audit failure).
7. Baseline EA Immutability (never modifies ea/TestEA.mq5).
8. NO global optimization, NO parameter brute-force, NO candidate scoreboards.
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.auditor import run_audit
from scripts.candidate_verifier import verify_candidate
from scripts.developer import run_developer
from scripts.developer_schemas import set_plan_approval
from scripts.experiment_planner import create_experiment_plan, save_experiment_plan
from scripts.research_context import build_research_context
from scripts.research_decision import (
    evaluate_research_decision,
    format_human_readable_decision,
)
from scripts.research_loop_schemas import (
    ALLOWED_STATES,
    APPROVAL_APPROVED,
    APPROVAL_EXPIRED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    DECISION_INFRASTRUCTURE_FAILURE,
    STATE_APPROVED,
    STATE_AUDITED,
    STATE_AUDITING,
    STATE_AWAITING_APPROVAL,
    STATE_BACKTESTING,
    STATE_BLOCKED,
    STATE_CANDIDATE_READY,
    STATE_COMPLETED,
    STATE_CREATED,
    STATE_DECIDED,
    STATE_DEVELOPING,
    STATE_EXPERIMENT_CREATED,
    STATE_FAILED,
    STATE_PLANNED,
    STATE_RESEARCHING,
    STATE_VALIDATION_AWAITING_APPROVAL,
    STATE_VALIDATION_APPROVED,
    STATE_VALIDATING,
    STATE_VALIDATED,
    get_next_iteration_id,
    validate_iteration_dict,
    validate_state_transition,
)
from scripts.research_periods import is_periods_configured, load_research_periods
from scripts.research_schemas import validate_experiment_plan_dict, validate_hypothesis_dict
from scripts.researcher import formulate_mock_hypothesis, save_hypothesis
from scripts.run_candidate import STATUS_SUCCESS, execute_candidate_backtest, execute_candidate_validation

# Default Directories
DEFAULT_ITERATIONS_DIR = PROJECT_ROOT / "research" / "iterations"
DEFAULT_HYPOTHESES_DIR = PROJECT_ROOT / "research" / "hypotheses"
DEFAULT_PLANS_DIR = PROJECT_ROOT / "research" / "plans"
DEFAULT_CANDIDATES_DIR = PROJECT_ROOT / "developer" / "candidates"
DEFAULT_EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
DEFAULT_AUDITS_DIR = PROJECT_ROOT / "audits"
DEFAULT_EA_DIR = PROJECT_ROOT / "ea"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"


class ResearchLoop:
    """
    Orchestrates the controlled autonomous research cycle across all AI EA Lab components.
    """

    def __init__(
        self,
        iterations_dir: Optional[Path] = None,
        hypotheses_dir: Optional[Path] = None,
        plans_dir: Optional[Path] = None,
        candidates_dir: Optional[Path] = None,
        experiments_dir: Optional[Path] = None,
        audits_dir: Optional[Path] = None,
        ea_dir: Optional[Path] = None,
        config_path: Optional[Path] = None,
        research_periods_path: Optional[Path] = None,
        mt5_launcher=None,
        developer_adapter=None,
        auditor_adapter=None,
    ):
        self.iterations_dir = Path(iterations_dir) if iterations_dir else DEFAULT_ITERATIONS_DIR
        self.hypotheses_dir = Path(hypotheses_dir) if hypotheses_dir else DEFAULT_HYPOTHESES_DIR
        self.plans_dir = Path(plans_dir) if plans_dir else DEFAULT_PLANS_DIR
        self.candidates_dir = Path(candidates_dir) if candidates_dir else DEFAULT_CANDIDATES_DIR
        self.experiments_dir = Path(experiments_dir) if experiments_dir else DEFAULT_EXPERIMENTS_DIR
        self.audits_dir = Path(audits_dir) if audits_dir else DEFAULT_AUDITS_DIR
        self.ea_dir = Path(ea_dir) if ea_dir else DEFAULT_EA_DIR
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.research_periods_path = (
            Path(research_periods_path) if research_periods_path else DEFAULT_RESEARCH_PERIODS_PATH
        )

        self.mt5_launcher = mt5_launcher
        self.developer_adapter = developer_adapter
        self.auditor_adapter = auditor_adapter

        # Ensure base directories exist
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        self.hypotheses_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_dir.mkdir(parents=True, exist_ok=True)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        self.audits_dir.mkdir(parents=True, exist_ok=True)

    def _record_transition(
        self,
        iteration: Dict[str, Any],
        to_state: str,
        reason: str = "",
    ) -> bool:
        """
        Validates and records a state machine transition on the iteration.
        """
        from_state = iteration.get("status", STATE_CREATED)
        is_valid, err_msg = validate_state_transition(from_state, to_state)
        if not is_valid:
            iteration["error"] = err_msg
            return False

        iteration["status"] = to_state
        iteration.setdefault("state_history", []).append({
            "from_state": from_state,
            "to_state": to_state,
            "timestamp": datetime.now().astimezone().isoformat(),
            "reason": reason,
        })
        return True

    def _save_iteration_artifacts(
        self,
        iteration_id: str,
        iteration_dict: Dict[str, Any],
        hypothesis: Optional[Dict[str, Any]] = None,
        plan: Optional[Dict[str, Any]] = None,
        approval: Optional[Dict[str, Any]] = None,
        candidate: Optional[Dict[str, Any]] = None,
        experiment: Optional[Dict[str, Any]] = None,
        audit: Optional[Dict[str, Any]] = None,
        decision: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Persists all artifacts for an iteration under research/iterations/ITER-XXXX/.
        """
        iter_dir = self.iterations_dir / iteration_id
        iter_dir.mkdir(parents=True, exist_ok=True)

        # Primary manifest
        (iter_dir / "iteration.json").write_text(
            json.dumps(iteration_dict, indent=2), encoding="utf-8"
        )

        if hypothesis:
            (iter_dir / "hypothesis.json").write_text(
                json.dumps(hypothesis, indent=2), encoding="utf-8"
            )

        if plan:
            (iter_dir / "plan.json").write_text(
                json.dumps(plan, indent=2), encoding="utf-8"
            )

        if approval:
            (iter_dir / "approval.json").write_text(
                json.dumps(approval, indent=2), encoding="utf-8"
            )

        if candidate:
            (iter_dir / "candidate.json").write_text(
                json.dumps(candidate, indent=2), encoding="utf-8"
            )

        if experiment:
            (iter_dir / "experiment.json").write_text(
                json.dumps(experiment, indent=2), encoding="utf-8"
            )

        if audit:
            (iter_dir / "audit.json").write_text(
                json.dumps(audit, indent=2), encoding="utf-8"
            )

        if decision:
            (iter_dir / "decision.json").write_text(
                json.dumps(decision, indent=2), encoding="utf-8"
            )

        return iter_dir

    def load_iteration(self, iteration_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads an iteration record from disk.
        """
        iter_file = self.iterations_dir / iteration_id / "iteration.json"
        if not iter_file.is_file():
            return None
        try:
            return json.loads(iter_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def create_iteration(
        self,
        hypothesis_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        question: Optional[str] = None,
        baseline_id: Optional[str] = None,
        mock: bool = True,
    ) -> Dict[str, Any]:
        """
        Initiates a new research iteration.
        Formulates hypothesis & plan if needed, creates memory artifacts,
        and halts safely at AWAITING_APPROVAL.
        """
        iter_id = get_next_iteration_id(self.iterations_dir)
        iter_dir = self.iterations_dir / iter_id
        iter_dir.mkdir(parents=True, exist_ok=True)

        now_iso = datetime.now().astimezone().isoformat()
        iteration: Dict[str, Any] = {
            "schema_version": 1,
            "iteration_id": iter_id,
            "created_at": now_iso,
            "completed_at": None,
            "status": STATE_CREATED,
            "approval_status": APPROVAL_PENDING,
            "approval": {
                "status": APPROVAL_PENDING,
                "reviewed_by": None,
                "reviewed_at": None,
                "note": "Awaiting explicit human approval before candidate development.",
            },
            "hypothesis_id": None,
            "plan_id": None,
            "candidate_id": None,
            "experiment_id": None,
            "audit_id": None,
            "decision": None,
            "provenance": {
                "hypothesis": None,
                "plan": None,
                "candidate": None,
                "experiment": None,
                "audit": None,
            },
            "state_history": [
                {
                    "from_state": "NONE",
                    "to_state": STATE_CREATED,
                    "timestamp": now_iso,
                    "reason": f"Created research iteration '{iter_id}'.",
                }
            ],
            "error": None,
        }

        hyp_data: Optional[Dict[str, Any]] = None
        plan_data: Optional[Dict[str, Any]] = None

        # Case 1: Plan provided directly
        if plan_id:
            plan_file = self.plans_dir / f"{plan_id}.json"
            if not plan_file.is_file():
                self._record_transition(iteration, STATE_FAILED, f"Plan file not found: {plan_file}")
                iteration["error"] = f"Plan '{plan_id}' does not exist on disk."
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            try:
                plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
            except Exception as e:
                self._record_transition(iteration, STATE_FAILED, f"Failed to load plan: {e}")
                iteration["error"] = f"Failed to parse plan JSON: {e}"
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            is_valid_plan, plan_issues = validate_experiment_plan_dict(plan_data)
            if not is_valid_plan:
                self._record_transition(iteration, STATE_FAILED, "Plan schema validation failed.")
                iteration["error"] = f"Plan validation failed: {'; '.join(plan_issues)}"
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            h_id = plan_data.get("hypothesis_id")
            if h_id:
                h_file = self.hypotheses_dir / f"{h_id}.json"
                if h_file.is_file():
                    try:
                        hyp_data = json.loads(h_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

            self._record_transition(iteration, STATE_PLANNED, f"Linked approved/planned plan '{plan_id}'.")

        # Case 2: Hypothesis provided, needs plan
        elif hypothesis_id:
            hyp_file = self.hypotheses_dir / f"{hypothesis_id}.json"
            if not hyp_file.is_file():
                self._record_transition(iteration, STATE_FAILED, f"Hypothesis file not found: {hyp_file}")
                iteration["error"] = f"Hypothesis '{hypothesis_id}' does not exist on disk."
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            try:
                hyp_data = json.loads(hyp_file.read_text(encoding="utf-8"))
            except Exception as e:
                self._record_transition(iteration, STATE_FAILED, f"Failed to load hypothesis: {e}")
                iteration["error"] = f"Failed to parse hypothesis JSON: {e}"
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            is_valid_hyp, hyp_issues = validate_hypothesis_dict(hyp_data)
            if not is_valid_hyp:
                self._record_transition(iteration, STATE_FAILED, "Hypothesis validation failed.")
                iteration["error"] = f"Hypothesis validation failed: {'; '.join(hyp_issues)}"
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

            self._record_transition(iteration, STATE_RESEARCHING, f"Loaded hypothesis '{hypothesis_id}'.")

            # Generate experiment plan from hypothesis
            context = build_research_context(
                config_path=self.config_path,
                manifest_path=self.experiments_dir / "manifest.json",
                experiments_dir=self.experiments_dir,
                research_periods_path=self.research_periods_path,
            )
            try:
                plan_data = create_experiment_plan(
                    hypothesis=hyp_data,
                    context=context,
                    baseline_id=baseline_id,
                    plans_dir=self.plans_dir,
                )
                save_experiment_plan(plan_data, plans_dir=self.plans_dir)
                self._record_transition(iteration, STATE_PLANNED, f"Generated experiment plan '{plan_data['experiment_plan_id']}'.")
            except Exception as e:
                self._record_transition(iteration, STATE_FAILED, f"Plan creation failed: {e}")
                iteration["error"] = f"Plan generation failed: {e}"
                self._save_iteration_artifacts(iter_id, iteration, hypothesis=hyp_data)
                return iteration

        # Case 3: Autonomous formulation from research question / context
        else:
            self._record_transition(iteration, STATE_RESEARCHING, "Formulating research hypothesis from context.")
            context = build_research_context(
                config_path=self.config_path,
                manifest_path=self.experiments_dir / "manifest.json",
                experiments_dir=self.experiments_dir,
                research_periods_path=self.research_periods_path,
            )
            try:
                hyp_data = formulate_mock_hypothesis(
                    context=context,
                    research_question=question,
                    baseline_id=baseline_id,
                    hypotheses_dir=self.hypotheses_dir,
                )
                save_hypothesis(hyp_data, hypotheses_dir=self.hypotheses_dir)

                plan_data = create_experiment_plan(
                    hypothesis=hyp_data,
                    context=context,
                    baseline_id=baseline_id,
                    plans_dir=self.plans_dir,
                )
                save_experiment_plan(plan_data, plans_dir=self.plans_dir)
                self._record_transition(iteration, STATE_PLANNED, f"Formulated hypothesis and plan '{plan_data['experiment_plan_id']}'.")
            except Exception as e:
                self._record_transition(iteration, STATE_FAILED, f"Hypothesis/plan formulation failed: {e}")
                iteration["error"] = str(e)
                self._save_iteration_artifacts(iter_id, iteration)
                return iteration

        # Link IDs into iteration manifest
        if hyp_data:
            iteration["hypothesis_id"] = hyp_data.get("hypothesis_id")
            iteration["provenance"]["hypothesis"] = hyp_data.get("hypothesis_id")
        if plan_data:
            iteration["plan_id"] = plan_data.get("experiment_plan_id")
            iteration["provenance"]["plan"] = plan_data.get("experiment_plan_id")

        # Crucial: Progress to AWAITING_APPROVAL and stop safely
        self._record_transition(
            iteration,
            STATE_AWAITING_APPROVAL,
            "Halting at Human Approval Gate. Plan requires explicit human review and authorization."
        )

        approval_record = {
            "iteration_id": iter_id,
            "plan_id": iteration.get("plan_id"),
            "status": APPROVAL_PENDING,
            "reviewed_by": None,
            "reviewed_at": None,
            "note": "Awaiting explicit human approval.",
        }

        self._save_iteration_artifacts(
            iter_id,
            iteration,
            hypothesis=hyp_data,
            plan=plan_data,
            approval=approval_record,
        )

        return iteration

    def approve_iteration(
        self,
        iteration_id: str,
        reviewer: str = "Lead Quant",
        note: str = "Approved for controlled candidate development.",
    ) -> Dict[str, Any]:
        """
        Records human approval for an iteration and synchronizes approval to the underlying plan.
        """
        iteration = self.load_iteration(iteration_id)
        if not iteration:
            raise FileNotFoundError(f"Iteration '{iteration_id}' not found.")

        current_state = iteration.get("status")
        if current_state != STATE_AWAITING_APPROVAL:
            raise ValueError(
                f"Cannot approve iteration '{iteration_id}' in state '{current_state}'. "
                f"Iteration must be in '{STATE_AWAITING_APPROVAL}'."
            )

        now_iso = datetime.now().astimezone().isoformat()
        iteration["approval_status"] = APPROVAL_APPROVED
        iteration["approval"] = {
            "status": APPROVAL_APPROVED,
            "reviewed_by": reviewer,
            "reviewed_at": now_iso,
            "note": note,
        }

        # Synchronize with underlying experiment plan
        plan_id = iteration.get("plan_id")
        if plan_id:
            plan_file = self.plans_dir / f"{plan_id}.json"
            if plan_file.is_file():
                set_plan_approval(
                    plan_file,
                    status="approved",
                    approved_by=reviewer,
                    note=note,
                )

        self._record_transition(
            iteration,
            STATE_APPROVED,
            f"Explicit human approval granted by '{reviewer}'."
        )

        approval_record = {
            "iteration_id": iteration_id,
            "plan_id": plan_id,
            "status": APPROVAL_APPROVED,
            "reviewed_by": reviewer,
            "reviewed_at": now_iso,
            "note": note,
        }

        self._save_iteration_artifacts(
            iteration_id,
            iteration,
            approval=approval_record,
        )

        return iteration

    def reject_iteration(
        self,
        iteration_id: str,
        reviewer: str = "Lead Quant",
        note: str = "Rejected by reviewer.",
    ) -> Dict[str, Any]:
        """
        Records human rejection for an iteration and blocks execution.
        """
        iteration = self.load_iteration(iteration_id)
        if not iteration:
            raise FileNotFoundError(f"Iteration '{iteration_id}' not found.")

        current_state = iteration.get("status")
        if current_state != STATE_AWAITING_APPROVAL:
            raise ValueError(
                f"Cannot reject iteration '{iteration_id}' in state '{current_state}'. "
                f"Iteration must be in '{STATE_AWAITING_APPROVAL}'."
            )

        now_iso = datetime.now().astimezone().isoformat()
        iteration["approval_status"] = APPROVAL_REJECTED
        iteration["approval"] = {
            "status": APPROVAL_REJECTED,
            "reviewed_by": reviewer,
            "reviewed_at": now_iso,
            "note": note,
        }

        # Synchronize with underlying experiment plan
        plan_id = iteration.get("plan_id")
        if plan_id:
            plan_file = self.plans_dir / f"{plan_id}.json"
            if plan_file.is_file():
                set_plan_approval(
                    plan_file,
                    status="rejected",
                    approved_by=reviewer,
                    note=note,
                )

        self._record_transition(
            iteration,
            STATE_BLOCKED,
            f"Iteration rejected by reviewer '{reviewer}': {note}."
        )

        approval_record = {
            "iteration_id": iteration_id,
            "plan_id": plan_id,
            "status": APPROVAL_REJECTED,
            "reviewed_by": reviewer,
            "reviewed_at": now_iso,
            "note": note,
        }

        self._save_iteration_artifacts(
            iteration_id,
            iteration,
            approval=approval_record,
        )

        return iteration

    def run_iteration(
        self,
        iteration_id: str,
        dry_run: bool = False,
        mock: bool = True,
        allow_unconfigured_dates: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes an approved research iteration through:
        Developer -> Candidate Verifier -> Candidate Runner (MT5) -> Auditor -> Research Decision.
        """
        iteration = self.load_iteration(iteration_id)
        if not iteration:
            raise FileNotFoundError(f"Iteration '{iteration_id}' not found.")

        # 1. ENFORCE HUMAN APPROVAL GATE
        current_state = iteration.get("status")
        approval_status = iteration.get("approval_status")

        if approval_status != APPROVAL_APPROVED:
            err = (
                f"Execution halted: Iteration '{iteration_id}' is not approved (status: '{approval_status}'). "
                f"Run '--approve {iteration_id}' to explicitly authorize candidate development."
            )
            iteration["error"] = err
            self._save_iteration_artifacts(iteration_id, iteration)
            return iteration

        if current_state not in {STATE_APPROVED, STATE_CANDIDATE_READY, STATE_EXPERIMENT_CREATED, STATE_AUDITED}:
            err = f"Iteration '{iteration_id}' is in state '{current_state}', not ready for run."
            iteration["error"] = err
            self._save_iteration_artifacts(iteration_id, iteration)
            return iteration

        plan_id = iteration.get("plan_id")
        candidate_record: Optional[Dict[str, Any]] = None
        exp_record: Optional[Dict[str, Any]] = None
        audit_record: Optional[Dict[str, Any]] = None
        decision_record: Optional[Dict[str, Any]] = None

        # 2. CANDIDATE DEVELOPMENT (if in STATE_APPROVED)
        if current_state == STATE_APPROVED:
            if not self._record_transition(iteration, STATE_DEVELOPING, "Executing AI Developer pipeline."):
                self._save_iteration_artifacts(iteration_id, iteration)
                return iteration

            dev_result = run_developer(
                plan_identifier=plan_id,
                dry_run=dry_run,
                mock=mock,
                plans_dir=self.plans_dir,
                candidates_dir=self.candidates_dir,
                experiments_dir=self.experiments_dir,
                ea_dir=self.ea_dir,
                adapter=self.developer_adapter,
            )
            candidate_record = dev_result

            if dev_result.get("status") in {"requires_plan_revision", "blocked"}:
                self._record_transition(
                    iteration,
                    STATE_BLOCKED,
                    f"Developer feasibility blocked: {dev_result.get('reason')}"
                )
                iteration["error"] = dev_result.get("reason")
                self._save_iteration_artifacts(iteration_id, iteration, candidate=candidate_record)
                return iteration

            if dev_result.get("status") != "ready_for_next_phase":
                self._record_transition(
                    iteration,
                    STATE_FAILED,
                    f"Developer execution failed: {dev_result.get('reason')}"
                )
                iteration["error"] = dev_result.get("reason")
                self._save_iteration_artifacts(iteration_id, iteration, candidate=candidate_record)
                return iteration

            cand_id = dev_result.get("candidate_id")
            iteration["candidate_id"] = cand_id
            iteration["provenance"]["candidate"] = cand_id

            if not self._record_transition(iteration, STATE_CANDIDATE_READY, f"Candidate '{cand_id}' developed and ready."):
                self._save_iteration_artifacts(iteration_id, iteration, candidate=candidate_record)
                return iteration

            if dry_run:
                self._save_iteration_artifacts(iteration_id, iteration, candidate=candidate_record)
                return iteration

            current_state = STATE_CANDIDATE_READY

        # 3. CANDIDATE VERIFICATION & BACKTEST EXECUTION
        if current_state == STATE_CANDIDATE_READY:
            cand_id = iteration.get("candidate_id")

            # Pre-flight candidate verification
            verif = verify_candidate(
                candidate_id=cand_id,
                candidates_dir=self.candidates_dir,
                plans_dir=self.plans_dir,
                experiments_dir=self.experiments_dir,
            )
            if not verif["verified"]:
                self._record_transition(
                    iteration,
                    STATE_FAILED,
                    f"Candidate verification failed: {'; '.join(verif['issues'])}"
                )
                iteration["error"] = f"Candidate verification failed: {'; '.join(verif['issues'])}"
                self._save_iteration_artifacts(iteration_id, iteration, candidate=verif)
                return iteration

            if not self._record_transition(iteration, STATE_BACKTESTING, f"Executing MT5 Strategy Tester for candidate '{cand_id}'."):
                self._save_iteration_artifacts(iteration_id, iteration)
                return iteration

            runner_result = execute_candidate_backtest(
                candidate_id=cand_id,
                dry_run=dry_run,
                verify_only=False,
                allow_unconfigured_dates=allow_unconfigured_dates,
                candidates_dir=self.candidates_dir,
                plans_dir=self.plans_dir,
                experiments_dir=self.experiments_dir,
                config_path=self.config_path,
                research_periods_path=self.research_periods_path,
                mt5_launcher=self.mt5_launcher,
            )

            if runner_result.get("status") != STATUS_SUCCESS or not runner_result.get("experiment", {}).get("created"):
                err_msg = runner_result.get("error") or f"Backtest failed with status: {runner_result.get('status')}"
                self._record_transition(iteration, STATE_FAILED, f"Backtest execution failed: {err_msg}")
                iteration["error"] = err_msg
                self._save_iteration_artifacts(iteration_id, iteration, experiment=runner_result)
                return iteration

            exp_id = runner_result["experiment"]["experiment_id"]
            iteration["experiment_id"] = exp_id
            iteration["provenance"]["experiment"] = exp_id
            exp_record = runner_result

            if not self._record_transition(iteration, STATE_EXPERIMENT_CREATED, f"Experiment '{exp_id}' created and verified."):
                self._save_iteration_artifacts(iteration_id, iteration, experiment=exp_record)
                return iteration

            current_state = STATE_EXPERIMENT_CREATED

        # 4. AUDITING
        if current_state == STATE_EXPERIMENT_CREATED:
            exp_id = iteration.get("experiment_id")
            if not self._record_transition(iteration, STATE_AUDITING, f"Executing AI Auditor for experiment '{exp_id}'."):
                self._save_iteration_artifacts(iteration_id, iteration)
                return iteration

            audit = run_audit(
                experiment_id=exp_id,
                experiments_dir=self.experiments_dir,
                candidates_dir=self.candidates_dir,
                plans_dir=self.plans_dir,
                hypotheses_dir=self.hypotheses_dir,
                audits_dir=self.audits_dir,
                research_periods_path=self.research_periods_path,
                adapter=self.auditor_adapter,
                force=True,
            )
            audit_id = audit.get("audit_id")
            iteration["audit_id"] = audit_id
            iteration["provenance"]["audit"] = audit_id
            audit_record = audit

            if not self._record_transition(iteration, STATE_AUDITED, f"Audit '{audit_id}' completed with status: {audit.get('status')}."):
                self._save_iteration_artifacts(iteration_id, iteration, audit=audit_record)
                return iteration

            current_state = STATE_AUDITED

        # 5. RESEARCH DECISION ENGINE
        if current_state == STATE_AUDITED:
            if not self._record_transition(iteration, STATE_DECIDED, "Evaluating structured research decision."):
                self._save_iteration_artifacts(iteration_id, iteration)
                return iteration

            # Load metrics and metadata for decision engine
            exp_id = iteration.get("experiment_id")
            exp_dir = self.experiments_dir / exp_id
            exp_metrics = {}
            exp_meta = {}
            if (exp_dir / "metrics.json").is_file():
                try:
                    exp_metrics = json.loads((exp_dir / "metrics.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
            if (exp_dir / "metadata.json").is_file():
                try:
                    exp_meta = json.loads((exp_dir / "metadata.json").read_text(encoding="utf-8"))
                except Exception:
                    pass

            plan_dict = {}
            if plan_id:
                plan_file = self.plans_dir / f"{plan_id}.json"
                if plan_file.is_file():
                    try:
                        plan_dict = json.loads(plan_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass

            periods_cfg = load_research_periods(self.research_periods_path)

            decision = evaluate_research_decision(
                audit=audit_record,
                metrics=exp_metrics,
                metadata=exp_meta,
                plan=plan_dict,
                periods_config=periods_cfg,
            )
            iteration["decision"] = decision
            decision_record = decision

            # Completion evaluation
            if decision.get("decision") == DECISION_INFRASTRUCTURE_FAILURE:
                self._record_transition(
                    iteration,
                    STATE_FAILED,
                    f"Iteration marked FAILED due to infrastructure failure: {decision.get('summary')}"
                )
            else:
                self._record_transition(
                    iteration,
                    STATE_COMPLETED,
                    f"Research cycle successfully completed. Decision: {decision.get('decision')}."
                )
                iteration["completed_at"] = datetime.now().astimezone().isoformat()

        # Save all artifacts
        self._save_iteration_artifacts(
            iteration_id,
            iteration,
            candidate=candidate_record,
            experiment=exp_record,
            audit=audit_record,
            decision=decision_record,
        )

        return iteration

    def list_iterations(self) -> List[Dict[str, Any]]:
        """
        Lists all iterations recorded in research/iterations/.
        """
        records = []
        if not self.iterations_dir.is_dir():
            return records

        for item in sorted(self.iterations_dir.iterdir()):
            if item.is_dir() and item.name.startswith("ITER-"):
                iter_file = item / "iteration.json"
                if iter_file.is_file():
                    try:
                        data = json.loads(iter_file.read_text(encoding="utf-8"))
                        records.append(data)
                    except Exception:
                        pass
        return records


def format_human_readable_iteration(iteration: Dict[str, Any]) -> str:
    """
    Formats the iteration record for clean console reporting.
    """
    iter_id = iteration.get("iteration_id", "UNKNOWN")
    status = iteration.get("status", "UNKNOWN")
    appr = iteration.get("approval", {})
    appr_status = iteration.get("approval_status", "UNKNOWN")
    hyp_id = iteration.get("hypothesis_id") or "None"
    plan_id = iteration.get("plan_id") or "None"
    cand_id = iteration.get("candidate_id") or "None"
    exp_id = iteration.get("experiment_id") or "None"
    audit_id = iteration.get("audit_id") or "None"
    decision = iteration.get("decision") or {}
    decision_val = decision.get("decision") or "Pending"

    lines = [
        "=" * 65,
        "AI-EA-LAB -- CONTROLLED AUTONOMOUS RESEARCH LOOP (PHASE 11)",
        "=" * 65,
        f"Iteration ID:     {iter_id}",
        f"State Machine:    {status}",
        f"Approval Status:  {appr_status} (Reviewed by: {appr.get('reviewed_by') or 'None'})",
        f"Created At:       {iteration.get('created_at')}",
        f"Completed At:     {iteration.get('completed_at') or 'In Progress'}",
        "",
        "--- PROVENANCE CHAIN ---",
        f"  Hypothesis:     {hyp_id}",
        f"  Plan:           {plan_id}",
        f"  Candidate:      {cand_id}",
        f"  Experiment:     {exp_id}",
        f"  Audit:          {audit_id}",
        f"  Decision:       {decision_val}",
        "",
    ]

    if decision:
        lines.append("--- DECISION SUMMARY ---")
        lines.append(f"  Outcome:        {decision.get('decision')}")
        lines.append(f"  Summary:        {decision.get('summary')}")
        lines.append(f"  Next Action:    {decision.get('next_action')}")
        lines.append("")

    if iteration.get("error"):
        lines.append("--- ERROR NOTICES ---")
        lines.append(f"  ! {iteration['error']}")
        lines.append("")

    lines.append("--- STATE TRANSITION HISTORY ---")
    for step in iteration.get("state_history", []):
        lines.append(f"  [{step.get('from_state')} -> {step.get('to_state')}]: {step.get('reason')}")

    lines.append("=" * 65)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="AI-EA-Lab Phase 11: Controlled Autonomous Research Loop Orchestrator"
    )
    parser.add_argument("--create", action="store_true", help="Initiate a new research iteration")
    parser.add_argument("--hypothesis", default=None, help="Hypothesis ID (HYP-XXXX) or trigger hypothesis creation")
    parser.add_argument("--plan", default=None, help="Plan ID (PLAN-XXXX)")
    parser.add_argument("--question", "-q", default=None, help="Research question for autonomous hypothesis generation")
    parser.add_argument("--baseline", default=None, help="Baseline experiment ID (e.g. EXP-0002)")
    parser.add_argument("--approve", default=None, help="Approve an iteration (ITER-XXXX)")
    parser.add_argument("--reject", default=None, help="Reject an iteration (ITER-XXXX)")
    parser.add_argument("--reviewer", default="Lead Quant", help="Human reviewer name for approval/rejection")
    parser.add_argument("--note", default="Approved", help="Human reviewer annotation note")
    parser.add_argument("--run", default=None, help="Execute an approved iteration (ITER-XXXX)")
    parser.add_argument("--dry-run", action="store_true", help="Preview iteration without modifying files or MT5")
    parser.add_argument("--mock", action="store_true", default=True, help="Use mock adapters for developer/auditor")
    parser.add_argument("--real", action="store_true", help="Use real MetaEditor compiler and real auditor")
    parser.add_argument("--allow-unconfigured-dates", action="store_true", help="Allow fallback backtest dates from plan")
    parser.add_argument("--status", nargs="?", const="ALL", default=None, help="Display status of an iteration or all iterations")
    parser.add_argument("--json", nargs="?", const="ALL", default=None, help="Output JSON for an iteration or all iterations")

    args = parser.parse_args()
    loop = ResearchLoop()
    use_mock = not args.real

    # 1. Status Command
    if args.status:
        if args.status == "ALL":
            all_iters = loop.list_iterations()
            if not all_iters:
                print("No research iterations found in archive.")
                return
            for it in all_iters:
                print(format_human_readable_iteration(it))
                print()
        else:
            it = loop.load_iteration(args.status)
            if not it:
                print(f"Error: Iteration '{args.status}' not found.")
                sys.exit(1)
            print(format_human_readable_iteration(it))
        return

    # 2. JSON Command
    if args.json:
        if args.json == "ALL":
            print(json.dumps(loop.list_iterations(), indent=2))
        else:
            it = loop.load_iteration(args.json)
            if not it:
                print(json.dumps({"error": f"Iteration '{args.json}' not found."}, indent=2))
                sys.exit(1)
            print(json.dumps(it, indent=2))
        return

    # 3. Approve Command
    if args.approve:
        try:
            res = loop.approve_iteration(args.approve, reviewer=args.reviewer, note=args.note)
            print(f"Iteration '{args.approve}' APPROVED by '{args.reviewer}'.")
            print(f"State transition: AWAITING_APPROVAL -> APPROVED.")
            print(f"Next step: Execute iteration using: python scripts/research_loop.py --run {args.approve}")
        except Exception as e:
            print(f"Approval failed: {e}")
            sys.exit(1)
        return

    # 4. Reject Command
    if args.reject:
        try:
            res = loop.reject_iteration(args.reject, reviewer=args.reviewer, note=args.note)
            print(f"Iteration '{args.reject}' REJECTED by '{args.reviewer}'.")
            print(f"State transition: AWAITING_APPROVAL -> BLOCKED.")
        except Exception as e:
            print(f"Rejection failed: {e}")
            sys.exit(1)
        return

    # 5. Run Command
    if args.run:
        try:
            res = loop.run_iteration(
                args.run,
                dry_run=args.dry_run,
                mock=use_mock,
                allow_unconfigured_dates=args.allow_unconfigured_dates,
            )
            print(format_human_readable_iteration(res))
            if res.get("decision"):
                print()
                print(format_human_readable_decision(res["decision"]))
        except Exception as e:
            print(f"Execution failed: {e}")
            sys.exit(1)
        return

    # 6. Create / Convenience Command
    if args.create or args.hypothesis or args.plan or args.question:
        try:
            res = loop.create_iteration(
                hypothesis_id=args.hypothesis,
                plan_id=args.plan,
                question=args.question,
                baseline_id=args.baseline,
                mock=use_mock,
            )
            print(format_human_readable_iteration(res))
            print()
            print("=================================================================")
            print("★ HUMAN APPROVAL BOUNDARY: EXECUTION SAFELY HALTED ★")
            print(f"Iteration '{res['iteration_id']}' is awaiting explicit human approval.")
            print(f"To approve, run:")
            print(f"  python scripts/research_loop.py --approve {res['iteration_id']}")
            print("=================================================================")
        except Exception as e:
            print(f"Iteration creation failed: {e}")
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
