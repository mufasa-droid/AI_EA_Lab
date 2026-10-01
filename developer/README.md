# AI-EA-Lab — AI Developer (Phase 8)

The **AI Developer** is the controlled code implementation layer of the AI-EA-Lab quantitative research pipeline. It consumes a **human-approved** Experiment Specification (`PLAN-XXXX`), verifies baseline and EA feasibility, applies authorized source changes, validates that no unauthorized modifications occurred, compiles the candidate using MetaEditor, and archives a complete, reproducible candidate artifact (`CAND-XXXX`).

---

## Architecture Position

```
                ┌───────────────────────────────────┐
                │           AI RESEARCHER           │
                │  • reads historical evidence      │
                │  • formulates testable hypothesis │
                └─────────────────┬─────────────────┘
                                  ↓
                ┌───────────────────────────────────┐
                │        EXPERIMENT PLANNER         │
                │  • controlled experiment design   │
                │  • isolated independent variable  │
                └─────────────────┬─────────────────┘
                                  ↓
                ┌───────────────────────────────────┐
                │     EXPERIMENT SPECIFICATION      │
                │      (research/plans/PLAN-XXXX)   │
                └─────────────────┬─────────────────┘
                                  ↓
                  =================================
                  ★ HUMAN APPROVAL BOUNDARY ★
                  =================================
                                  ↓
                ┌───────────────────────────────────┐
                │           AI DEVELOPER            │
                │  • verifies explicit approval     │
                │  • validates plan & baseline      │
                │  • analyzes EA feasibility        │
                │  • creates candidate workspace    │
                │  • modifies ONLY authorized inputs│
                │  • generates unified diff         │
                │  • performs static validation     │
                │  • compiles via MetaEditor        │
                │  • archives development artifact  │
                └─────────────────┬─────────────────┘
                                  ↓
                ┌───────────────────────────────────┐
                │        CANDIDATE ARTIFACT         │
                │   (developer/candidates/CAND-XXXX)│
                └─────────────────┬─────────────────┘
                                  ↓
                       [FUTURE AUDITOR PHASE]
```

---

## 1. What the Developer Does

1. **Enforces Human Approval**: Checks for an explicit `"approval": {"status": "approved"}` block in the target plan. Never executes unapproved plans.
2. **Validates Plan & Baseline**: Verifies that the plan conforms to schema rules, the baseline experiment exists in `experiments/`, and baseline parameter values match.
3. **Conducts Technical Feasibility Analysis**: Inspects the target EA source code. If an experiment expects trade-based observations (e.g. `total_trades > 0`) but the EA's `OnTick()` lacks trading logic, it flags the plan as `REQUIRES_PLAN_REVISION` and does **not** alter source code.
4. **Preserves Baseline Source**: The canonical EA file in `ea/` is never overwritten. The baseline source is preserved in `source_before.mq5`.
5. **Applies Controlled Changes**: Modifies **only** authorized input parameters specified in the approved plan.
6. **Generates Diffs & Manifests**: Produces `diff.patch` and `change_manifest.json` recording every applied change.
7. **Performs Static Change Validation**: Scans before/after diffs to ensure no unauthorized variables, functions, preprocessor directives, or logic were altered.
8. **Compiles with MetaEditor**: Executes `metaeditor64.exe` to compile candidate source, captures compiler return codes and UTF-16 logs, and records errors/warnings.
9. **Archives Candidate Artifacts**: Preserves each candidate deterministically under `developer/candidates/CAND-XXXX/`.

---

## 2. What the Developer Does NOT Do

* **Does NOT trade live**: No broker connections, no order placement, no account operations.
* **Does NOT modify credentials**: Never touches login settings, passwords, or broker servers.
* **Does NOT invent trading logic**: If an EA lacks trade execution in `OnTick()`, the Developer reports the incompatibility rather than fabricating entry rules.
* **Does NOT perform parameter sweeps**: No genetic algorithms or brute-force curve fitting.
* **Does NOT rewrite historical experiments**: `EXP-0001` and `EXP-0002` are immutable historical records.
* **Does NOT declare strategy winners**: The Developer only verifies candidate correctness, not market efficacy.
* **Does NOT auto-run backtests**: Keeps the build phase separate from strategy testing.

---

## 3. Human Approval Boundary

A plan requires explicit human approval before any implementation occurs.

### Approval State Format
```json
{
  "approval": {
    "status": "approved",
    "reviewed_by": "Lead Quant",
    "reviewed_at": "2026-09-29T10:42:16.193740+01:00",
    "note": "Approved for sensitivity testing"
  }
}
```

If `approval` is missing or status is `pending` or `rejected`, the Developer immediately halts:
```text
Approval:
    PENDING (Human approval required)

Action:
    Execution halted. Plans cannot be implemented without explicit human approval.

Status:
    APPROVAL_REQUIRED
```

### Approving and Revoking Plans via CLI
```bash
# Approve a plan
python scripts/developer.py --approve PLAN-0001 --reviewer "Lead Quant" --note "Approved"

# Revoke approval
python scripts/developer.py --revoke PLAN-0001
```

---

## 4. Candidate Artifact Structure

Candidates are saved under `developer/candidates/CAND-XXXX/` with monotonically incrementing IDs:

```
developer/candidates/
└── CAND-0001/
    ├── source_before.mq5      # Exact copy of baseline EA source before edits
    ├── source_after.mq5       # Candidate EA source with only authorized changes
    ├── source_after.ex5       # Compiled MQL5 binary (when MetaEditor is available)
    ├── diff.patch             # Unified diff showing exact line changes
    ├── change_manifest.json   # Structured manifest of authorized and unauthorized changes
    ├── feasibility.json       # Technical feasibility analysis results
    ├── compile.log            # Raw MetaEditor compiler output log
    └── metadata.json          # Complete candidate metadata and validation audit trail
```

---

## 5. Feasibility Analysis & The TestEA Case

The Developer prevents futile or corrupt experiments by validating architectural feasibility before touching code.

### The TestEA Limitation
`ea/TestEA.mq5` is intentionally a pipeline stub with an empty `OnTick()`:
```cpp
void OnTick()
{
   // Intentionally simple for pipeline testing.
   // Trading logic will be added later.
}
```
If an experiment plan (such as `PLAN-0001`) requests changing `FastMAPeriod: 10 -> 5` expecting `total_trades > 0`, the Developer reports:

```text
Feasibility:
    REQUIRES_PLAN_REVISION

Reason:
    The requested parameter exists, but the current EA does not contain
    trading/signal execution logic that uses the MA handles. Therefore
    the plan's expected trade-based observation cannot currently be produced
    by changing FastMAPeriod alone.

Action:
    No source modification performed.
```

The Developer **never** adds `OrderSend()` calls automatically to make a plan seem viable.

---

## 6. Static Change Validation

Static change validation verifies:
1. Every modified line corresponds to an authorized parameter in `changes_under_test`.
2. No unauthorized input defaults were changed.
3. No functions (`OnInit`, `OnTick`, `OnDeinit`) were modified.
4. No preprocessor directives (`#property`, `#include`, `#define`) were modified.
5. If any unauthorized change is detected, candidate validation fails immediately with `status: validation_failed`.

---

## 7. MQL5 Compilation

The compilation engine discovers `metaeditor64.exe` using `config.json`'s terminal path or standard system directories:

```cmd
metaeditor64.exe /compile:"path\to\source_after.mq5" /log:"path\to\compile.log"
```

Compilation features:
* UTF-16 log parsing extracting exact error and warning counts.
* Line-by-line syntax error reporting.
* `.ex5` binary verification and archival.
* Graceful fallback when MetaEditor is not installed (`compile_status: "unavailable"`).

---

## 8. CLI Usage

### Running Developer on an Approved Plan
```bash
python scripts/developer.py --plan PLAN-0001
```

### Dry-Run Mode
Simulates the entire workflow without creating candidate files or modifying any source:
```bash
python scripts/developer.py --plan PLAN-0001 --dry-run
```

### Machine-Readable JSON Mode
```bash
python scripts/developer.py --plan PLAN-0001 --json
```

### Checking Status of Plans and Candidates
```bash
python scripts/developer.py --status
```

---

## 9. Future Integration (Phase 9)

Phase 8 ends at verified candidate creation and compilation.
In Phase 9, approved candidate binaries will be routed into the automated Strategy Tester backtesting pipeline (`scripts/backtest.py`), parsed, and indexed as verified experiments (`EXP-XXXX`).
