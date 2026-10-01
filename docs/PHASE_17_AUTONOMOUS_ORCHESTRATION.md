# PHASE 17 — FULL AUTONOMOUS RESEARCH ORCHESTRATION

## System Overview

Phase 17 establishes the **Research Orchestration Layer** (`scripts/research_orchestrator.py`), unifying all preceding AI-EA-Lab components into a controlled, stateful, and restartable autonomous research system.

The Orchestrator manages multi-iteration research loops through strict sequential stages:

```
┌─────────────────────────────────────────────────────────┐
│                 RESEARCH ORCHESTRATOR                   │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      AI RESEARCHER                      │
│            (Formulates hypothesis & basis)              │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                   EXPERIMENT PLANNER                    │
│            (Creates controlled PLAN-XXXX)               │
└────────────────────────────┬────────────────────────────┘
                             │
              ===============================
              ★ HUMAN APPROVAL BOUNDARY ★
              ===============================
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      AI DEVELOPER                       │
│        (Implements candidate & compiles MQL5)           │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                  CANDIDATE VERIFIER                     │
│         (Validates diff, hashes, & provenance)          │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                MT5 TESTER / RUNNER                      │
│        (Executes isolated backtest & archives)          │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                      AI AUDITOR                         │
│           (Evaluates multi-dimensional evidence)        │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                   MEMORY INGESTION                      │
│        (Ingests facts, observations, & findings)        │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────┐
│                 RESEARCH DECISION ENGINE                │
│    (Determines: CONTINUE_RESEARCH, REVISE_PLAN, etc.)   │
└────────────────────────────┬────────────────────────────┘
                             │
                             ▼
                      NEXT ITERATION
```

---

## 1. Orchestration Principles & Boundaries

1. **Strict Human Approval Gate**: When `approval_required: true` (default), the orchestrator halts at `AWAITING_APPROVAL` before invoking AI Developer code modification.
2. **Plan-Bound Approval**: Approval is cryptographically bound to a specific `plan_id`. If plan contents change, approval becomes invalid.
3. **Persisted State Engine**: Orchestrator state is saved atomically to `research/orchestrator/runs/ORCH-XXXX/state.json`. A process crash or system restart loads state and resumes safely without duplicating work.
4. **Append-Only Audit Event Log**: Transitions emit events into `events.jsonl`. Event history is immutable.
5. **Resource Locking**: `OrchestratorResourceLock` prevents concurrent orchestrator processes from conflicting over MT5 Strategy Tester port 3000 or staging resources.
6. **Bounded Research Budgets**: Enforces limits on `maximum_iterations`, `maximum_failures`, and retries.
7. **Infrastructure vs Strategy Failure Separation**: Distinguishes process/compiler crashes from strategy findings.
8. **UNSEEN Protection**: The `unseen` dataset partition remains protected and is never loaded automatically.

---

## 2. Orchestration State Machine

```
ORCHESTRATOR_CREATED
       ↓
  RESEARCHING ───(Hypothesis created)───► HYPOTHESIS_CREATED
                                                ↓
   PLANNING   ───(Plan created)─────────► PLAN_CREATED
                                                ↓
  AWAITING_APPROVAL ◄───────────────────(Approval Gate)
       ↓ (Explicit Human Approval)
   APPROVED
       ↓
  DEVELOPING  ───(Candidate created)───► CANDIDATE_CREATED
                                                ↓
VERIFYING_CANDIDATE ──(Verified)────────► CANDIDATE_VERIFIED
                                                ↓
   EXECUTING  ───(Experiment created)──► EXPERIMENT_CREATED
                                                ↓
   AUDITING   ───(Audited)─────────────► AUDITED
                                                ↓
INGESTING_MEMORY ─(Memory updated)─────► MEMORY_UPDATED
                                                ↓
   DECIDING   ───(Decision created)────► DECISION_CREATED
                                                ↓
                                      ITERATION_COMPLETED
                                                ↓
                                      (Next Iteration / Stop)
```

---

## 3. Directory & Persistence Structure

```
research/
└── orchestrator/
    ├── orchestrator.lock     # Process lock preventing MT5 resource contention
    └── runs/
        └── ORCH-0001/
            ├── state.json           # Atomic state snapshot
            ├── events.jsonl         # Immutable append-only transition event log
            ├── configuration.json   # Configuration parameters snapshot
            └── summary.json         # Run summary manifest upon completion
```

---

## 4. CLI Usage

```bash
# Initialize a new orchestrator run
python scripts/research_orchestrator.py --init

# Initialize in dry-run mode (simulates workflow path without launching MT5)
python scripts/research_orchestrator.py --init --dry-run

# Run orchestrator up to human approval or stop condition
python scripts/research_orchestrator.py --run ORCH-0001

# Grant explicit human approval for a plan
python scripts/research_orchestrator.py --run ORCH-0001 --approve PLAN-0001 --reviewer "Lead Quant"

# Inspect status of an orchestrator run
python scripts/research_orchestrator.py --status ORCH-0001
```

---

## 5. Non-Goals & Safety Commitments

- **NO Live Trading**: Strictly offline research environment.
- **NO Order Execution**: No broker connectivity or execution calls.
- **NO Strategy Scoreboards**: No ranking candidates as "winners" or "losers".
- **NO Unrestricted Sweeps**: No brute-force parameter curve fitting.
