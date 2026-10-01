# AI-EA-Lab: Experiment Intelligence & Architecture Guide

## System Overview

AI-EA-Lab is an automated quantitative research and backtesting laboratory for MetaTrader 5 (MT5) Expert Advisors (EAs).
The laboratory provides an end-to-end reproducible research pipeline:

```
                ┌───────────────────────────────────┐
                │           AI RESEARCHER           │
                │                                   │
                │  • reads historical evidence      │
                │  • separates facts vs inferences  │
                │  • formulates testable hypothesis │
                └─────────────────┬─────────────────┘
                                  ↓
                ┌───────────────────────────────────┐
                │        EXPERIMENT PLANNER         │
                │                                   │
                │  • controlled experiment design   │
                │  • baseline comparison reference  │
                │  • 1 primary variable at a time   │
                │  • duplicate detection            │
                │  • dataset partition assignment   │
                │  • falsification conditions       │
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
                │            (Phase 8)              │
                │  • verifies explicit approval     │
                │  • validates baseline & EA        │
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
                ┌───────────────────────────────────┐
                │        AI BACKTEST RUNNER         │
                │            (Phase 9)              │
                │  • verifies candidate & provenance│
                │  • stages isolated binary in MT5  │
                │  • checks port 3000 conflict      │
                │  • runs Strategy Tester backtest  │
                │  • verifies report & anti-contam. │
                │  • parses metrics & validation    │
                │  • archives new experiment EXP-XXXX│
                │  • updates manifest catalog       │
                └─────────────────┬─────────────────┘
                                  ↓
                        MT5 Strategy Tester
                                  ↓
                      Verified HTML Report (.htm)
                                  ↓
                     Structured Parser & Archive
                                  ↓
                     Experiment Intelligence Layer
                       ├── Manifest Indexer
                       ├── Experiment Comparator
                       ├── Research Periods Classifier
                       └── Data Integrity Validator
                                  ↓
                ┌───────────────────────────────────┐
                │             AI AUDITOR            │
                │            (Phase 10)             │
                │  • audits experiment identity     │
                │  • verifies unbroken provenance   │
                │  • re-checks cryptographic hashes │
                │  • validates tester execution     │
                │  • verifies report consistency    │
                │  • checks plan compliance         │
                │  • audits candidate change scope  │
                │  • evaluates dataset status       │
                │  • rates reproducibility          │
                │  • evaluates overfitting & risks  │
                │  • archives audit (AUD-XXXX)      │
                └─────────────────┬─────────────────┘
                                  ↓
                          AI Researcher Loop
```

> **IMPORTANT BOUNDARY:**
> This system is strictly an offline research and backtesting environment.
> It does **NOT** engage in live trading, broker account balance risk, or automated order execution.
> Autonomous MQL5 code generation, parameter sweeps, and genetic optimization are deferred to subsequent phases.

---

## Agent Role Clarification

In the AI-EA-Lab architecture, roles are strictly partitioned to maintain research integrity:

| Role | Responsibility | Boundaries |
| :--- | :--- | :--- |
| **AI RESEARCHER** | Answers: *"What should we test next, and why?"* Formulates testable hypotheses from observed facts. | **Does NOT modify code.** Does NOT execute backtests. Does NOT invent data. |
| **EXPERIMENT PLANNER** | Translates hypothesis into a controlled Experiment Specification (`PLAN-XXXX`). Enforces baseline & controls. | **Does NOT write MQL5.** Stops at specification. Requires human review. |
| **AI DEVELOPER** *(Phase 8)* | Converts HUMAN-APPROVED plans into reproducible MQL5 candidates; executes feasibility analysis; enforces controlled-change rule; compiles via MetaEditor; archives candidates (`CAND-XXXX`). | **Does NOT modify code without human approval.** Does NOT invent trading logic. Does NOT execute backtests or live trades. Does NOT deploy to MT5. |
| **AI BACKTEST RUNNER** *(Phase 9)* | Executes controlled MT5 backtests for verified candidates; verifies provenance, binaries, and reports; isolates staged candidate binaries; parses results into structured metrics; archives reproducible experiments (`EXP-XXXX`). | **Does NOT make strategy decisions.** Does NOT declare winners or rank candidates. Does NOT execute live trades or connect to live broker accounts. Does NOT alter credentials. |
| **AI AUDITOR** *(Phase 10)* | Evaluates whether backtest outcomes provide valid, reproducible, and plan-compliant empirical evidence; evaluates methodological risks (overfitting, leakage); archives audits (`AUD-XXXX`). | **Does NOT rank candidates.** Does NOT declare winners or optimal strategies. Does NOT compute composite scores. Does NOT execute live trades or alter code. |
| **OPTIMIZER** *(Intentionally Excluded)* | Parameter curve-fitting algorithms (e.g. brute force / genetic sweeps). | **NOT ALLOWED.** Prevents data mining and catastrophic overfitting. |

---

## Experiment Archive Structure

Each experiment is permanently archived under `experiments/EXP-XXXX/` with guaranteed non-overwriting, monotonic IDs:

```
experiments/
├── manifest.json                  # Lightweight catalog of all valid experiments
├── EXP-0001/
│   ├── report.htm                 # Raw MT5 HTML strategy tester report (UTF-16LE or UTF-8)
│   ├── metrics.json               # Extracted structured metrics and validation flags
│   ├── metadata.json              # Run configuration, Git commit, EA checksums, parameters
│   └── charts/                    # Generated charts (holding time, balance/equity, MFE/MAE)
└── EXP-0002/
    ├── report.htm
    ├── metrics.json
    ├── metadata.json
    └── charts/
```

### Experiment Metadata (`metadata.json`)
Records reproducible parameters:
- `experiment_id`: Unique identifier (e.g. `EXP-0001`)
- `created_at`: ISO 8601 timestamp with timezone
- `note`: User or system annotation
- `ea`: EA identifier name
- `symbol`, `timeframe`, `from`, `to`: Market test window
- `ea_source` & `ea_binary`: Filenames, sizes, modification timestamps, and SHA-256 hashes
- `backtest_config`: Deposit, currency, leverage, tester execution model
- `inputs`: EA input parameters (e.g. `FastMAPeriod`, `SlowMAPeriod`, `LotSize`)
- `git_commit`: Current commit hash (if inside git repository)
- `status`: Execution state (`COMPLETED`)

### Experiment Metrics (`metrics.json`)
Parsed directly from the verified MT5 report:
- `settings`: Cleaned backtest parameters
- `metrics`: Market/data quality (`history_quality_percent`, `bars`, `ticks`), performance (`total_net_profit`, `gross_profit`, `gross_loss`, `profit_factor`, `expected_payoff`, `recovery_factor`, `sharpe_ratio`), drawdown metrics, trade breakdown (counts, win rates, averages)
- `validation`: `report_non_empty`, `history_quality_100`, `bars_present`, `ticks_present`, `test_executed`

---

## Experiment Manifest (`experiments/manifest.json`)

The manifest provides a fast, lightweight index of all experiments without requiring callers to parse individual reports or directory trees.

### Building / Rebuilding Manifest
The manifest is deterministically generated from experiment archives:

```bash
python scripts/build_manifest.py
```

---

## Experiment Comparison Tool (`scripts/compare_experiments.py`)

Compares two or more experiments side-by-side.

### Factual Comparison Philosophy
The tool strictly reports **factual differences**. It intentionally does **NOT**:
- Compute subjective "composite scores"
- Rank experiments
- Designate any experiment as "Best", "Winner", "Superior", "Optimal", or "Recommended"

### Usage
Human-readable report:
```bash
python scripts/compare_experiments.py EXP-0001 EXP-0002
```

Machine-readable JSON output:
```bash
python scripts/compare_experiments.py EXP-0001 EXP-0002 --json
```

---

## Research Periods Configuration (`config/research_periods.json`)

To prevent data snooping and model overfitting, research partitions are strictly defined:
- **TRAINING**: In-sample data for model fitting / parameter search
- **VALIDATION**: Selection and tuning evaluation
- **UNSEEN**: Strictly out-of-sample final benchmark

```json
{
  "schema_version": 1,
  "status": "unconfigured",
  "note": "Research period dates are unconfigured placeholders. Define actual YYYY.MM.DD date ranges before production partitioning.",
  "periods": {
    "training": {
      "from": null,
      "to": null
    },
    "validation": {
      "from": null,
      "to": null
    },
    "unseen": {
      "from": null,
      "to": null
    }
  }
}
```

---

## AI Researcher & Experiment Planner

The reasoning layer that sits above the experiment catalog to design scientifically controlled tests.

```
research/
├── hypotheses/        # Stored research hypotheses (HYP-XXXX.json)
├── plans/             # Stored experiment specifications (PLAN-XXXX.json)
├── context/           # Dynamic snapshots of unified research context
├── llm/               # Abstract LLM adapter interface
└── README.md          # Research repository documentation
```

### Fact vs Hypothesis Distinction

The system enforces strict categorization to avoid cognitive bias and unsupported claims:

1. **FACT**: An empirically verified observation from historical experiments (e.g., *"EXP-0002 recorded 0 trades on GBPUSD M15 across 2,120 bars"*).
2. **INFERENCE**: A logical deduction based on facts (e.g., *"The moving average crossover condition was not triggered during this period"*).
3. **HYPOTHESIS**: A testable proposition stating expected effect under controlled conditions (e.g., *"Reducing FastMAPeriod from 10 to 5 will increase signal sensitivity and produce more than 0 trades"*).
4. **EXPERIMENT**: The concrete configuration designed to test the hypothesis against a specified baseline.
5. **EXPECTED OBSERVATION**: Measurable metric outcomes that would support the hypothesis (e.g., *"Total trades > 0; profit factor becomes calculable"*).
6. **FALSIFICATION CONDITION**: Specific metric results that would invalidate or weaken the hypothesis (e.g., *"Total trades remain 0"*).

### No Profit Maximizer Rule
The Researcher does **NOT** seek to "maximize profit" or produce a single strategy score. It reasons from multi-dimensional observations:
- Trade count and execution frequency
- Market exposure and drawdown
- Parameter sensitivity and stability
- History quality, bars, and tick coverage
- Performance consistency across datasets

### Baseline Concept & Controlled Experiments
- Every proposed experiment plan must explicitly designate a `baseline` experiment (e.g. `EXP-0002`).
- The plan must isolate **one primary independent variable** at a time.
- If multiple variables are changed simultaneously, the Planner automatically attaches an explicit warning:
  `"Multiple independent variables are changing simultaneously; causal attribution may be difficult."`

### Duplicate Detection
The Planner scans all historical experiment inputs. If an experiment with identical parameters for the same EA, symbol, and timeframe was already executed, a duplicate warning is issued:
`"This configuration appears to duplicate existing experiment EXP-XXXX."`

### Human Approval Boundary
Experiment plans are generated with `status: "planned"` and `human_review_required: true`.
The system will **never** automatically apply code changes or run backtests without human authorization.

---

## Research Schemas

### 1. Research Hypothesis Schema (`research/hypotheses/HYP-XXXX.json`)
```json
{
  "schema_version": 1,
  "hypothesis_id": "HYP-0001",
  "created_at": "2026-09-29T00:21:48+01:00",
  "title": "Fast Moving Average Sensitivity Reduction Test",
  "research_question": "Does reducing FastMAPeriod from 10 to 5 increase crossover sensitivity and generate non-zero trades?",
  "hypothesis": "Reducing FastMAPeriod from 10 to 5 will increase signal sensitivity and result in more than 0 trades.",
  "basis": {
    "historical_experiments": ["EXP-0002", "EXP-0001"],
    "facts": ["EXP-0002 recorded exactly 0 trades across 2,120 bars."],
    "inferences": ["Current MA parameters did not cross during the test window."],
    "evidence": ["EXP-0002 total_trades=0, profit_factor=0.0"]
  },
  "independent_variables": [
    {
      "name": "FastMAPeriod",
      "baseline_value": "10",
      "proposed_value": "5",
      "rationale": "Shorter period increases responsiveness."
    }
  ],
  "dependent_variables": ["total_trades", "total_net_profit", "profit_factor"],
  "control_variables": [
    {"name": "SlowMAPeriod", "value": "20"},
    {"name": "LotSize", "value": "0.01"},
    {"name": "symbol", "value": "GBPUSD"},
    {"name": "timeframe", "value": "M15"}
  ],
  "assumptions": ["EA logic functions correctly when crossovers occur."],
  "dataset": {
    "type": "training",
    "from": "2024.01.01",
    "to": "2024.02.01",
    "status": "unconfigured"
  },
  "expected_observations": ["Total trades will increase from 0 to at least 1."],
  "falsification_conditions": ["Total trades remain exactly 0 after reducing FastMAPeriod to 5."],
  "status": "proposed"
}
```

### 2. Experiment Plan Schema (`research/plans/PLAN-XXXX.json`)
```json
{
  "schema_version": 1,
  "experiment_plan_id": "PLAN-0001",
  "hypothesis_id": "HYP-0001",
  "created_at": "2026-09-29T00:21:48+01:00",
  "title": "Fast Moving Average Sensitivity Reduction Test",
  "research_question": "Does reducing FastMAPeriod from 10 to 5 increase moving average crossover sensitivity?",
  "objective": "Test whether changing FastMAPeriod relative to baseline EXP-0002 produces expected observations.",
  "baseline": {
    "experiment_id": "EXP-0002",
    "ea": "TestEA",
    "symbol": "GBPUSD",
    "timeframe": "M15",
    "inputs": {"FastMAPeriod": "10", "SlowMAPeriod": "20", "LotSize": "0.01"}
  },
  "changes_under_test": [
    {
      "variable": "FastMAPeriod",
      "baseline_value": "10",
      "target_value": "5",
      "change_type": "parameter_adjustment"
    }
  ],
  "unchanged_variables": [
    {"variable": "SlowMAPeriod", "value": "20"},
    {"variable": "LotSize", "value": "0.01"}
  ],
  "parameters": {
    "FastMAPeriod": "5",
    "SlowMAPeriod": "20",
    "LotSize": "0.01"
  },
  "dataset": {
    "type": "training",
    "from": "2024.01.01",
    "to": "2024.02.01",
    "status": "unconfigured"
  },
  "observations": ["total_net_profit", "profit_factor", "total_trades", "history_quality_percent"],
  "expected_observations": ["Total trades will increase from 0 to at least 1."],
  "falsification_conditions": ["Total trades remain exactly 0."],
  "warnings": [],
  "risks": ["Overfitting if tested repeatedly on same window."],
  "human_review_required": true,
  "status": "planned"
}
```

---

## AI Developer Architecture (Phase 8)

The AI Developer is the controlled code implementation layer. It converts an **approved** Experiment Plan into a verified, compiled MQL5 candidate without manual code editing or unconstrained parameter drift.

```
developer/
├── candidates/
│   └── CAND-0001/
│       ├── source_before.mq5      # Untouched copy of baseline EA source
│       ├── source_after.mq5       # Candidate source with authorized changes
│       ├── source_after.ex5       # Compiled binary from MetaEditor
│       ├── diff.patch             # Unified diff
│       ├── change_manifest.json   # Authorized & unauthorized change record
│       ├── feasibility.json       # Feasibility analysis output
│       ├── compile.log            # MetaEditor UTF-16 compile output
│       └── metadata.json          # Complete candidate audit record
├── schemas/                       # JSON schemas for candidate artifacts
└── README.md                      # Developer documentation
```

### 1. Strict Human Approval Boundary
The Developer strictly enforces explicit human approval. Human approval **CANNOT** be inferred from `human_review_required: true`, plan creation, CLI invocation, or mock mode:

```json
"approval": {
  "status": "approved",
  "reviewed_by": "Lead Quant",
  "reviewed_at": "2026-09-29T10:42:16.193740+01:00"
}
```
If approval is missing, `pending`, or `rejected`, the Developer immediately halts with `status: APPROVAL_REQUIRED`.

### 2. Feasibility Analysis & The TestEA Limitation
Before modifying any source code, the Developer evaluates technical feasibility:
- Verifies that target parameters exist in the target EA's `input` declarations.
- Checks architectural compatibility: if an experiment plan expects trade-based observations (e.g. `total_trades > 0`, `profit_factor`, `drawdown`), but the target EA's `OnTick()` is empty or contains no order execution logic (as is the case with `ea/TestEA.mq5`), the Developer flags the plan as `REQUIRES_PLAN_REVISION`.
- **THE DEVELOPER NEVER INVENTS TRADING LOGIC AUTOMATICALLY.**

### 3. Controlled Changes & Static Change Validation
- Modifies **only** authorized input parameters specified in `changes_under_test`.
- Baseline EA in `ea/` is **never** overwritten.
- Static diff inspection confirms that no unauthorized inputs, functions (`OnInit`, `OnTick`), preprocessor directives (`#include`, `#property`), or global variables were modified.
- Any unauthorized modification triggers immediate candidate rejection (`status: validation_failed`).

### 4. MetaEditor Compilation Boundary
- Discovers installed `metaeditor64.exe`.
- Compiles `source_after.mq5` via CLI: `/compile:"<file>" /log:"<log>"`.
- Parses UTF-16 compiler logs to extract exact error and warning counts.
- Verifies `.ex5` binary generation and archives artifacts.
- Handles environments without MetaEditor gracefully (`compile_status: unavailable`).

---

## CLI Usage

### AI Researcher
```bash
python scripts/researcher.py --mock
python scripts/researcher.py --question "<text>"
python scripts/researcher.py --baseline EXP-0002 --json
```

### AI Developer (Phase 8)
```bash
# Execute candidate implementation for an approved plan
python scripts/developer.py --plan PLAN-0001

# Dry-run mode (validates feasibility and diff without writing files)
python scripts/developer.py --plan PLAN-0001 --dry-run

# Machine-readable JSON output
python scripts/developer.py --plan PLAN-0001 --json

# Human approval management
python scripts/developer.py --approve PLAN-0001 --reviewer "Lead Quant" --note "Approved"
python scripts/developer.py --revoke PLAN-0001

# Inspect status of plans and candidates
python scripts/developer.py --status
```

### AI Backtest Runner (Phase 9)
```bash
# Execute controlled backtest for a verified candidate
python scripts/run_candidate.py --candidate CAND-0001

# Dry-run mode (previews parameters and isolation without launching MT5)
python scripts/run_candidate.py --candidate CAND-0001 --dry-run

# Verification-only mode (validates hashes, binary, and provenance without backtesting)
python scripts/run_candidate.py --candidate CAND-0001 --verify-only

# Machine-readable JSON output
python scripts/run_candidate.py --candidate CAND-0001 --json
```

### AI Auditor (Phase 10)
```bash
# Execute evidence audit for an experiment
python scripts/auditor.py --experiment EXP-0003

# Machine-readable JSON output
python scripts/auditor.py --experiment EXP-0003 --json

# Force re-audit bypassing cached audit.json
python scripts/auditor.py --experiment EXP-0003 --force
```

---

## AI Backtest Runner & Candidate Verification (Phase 9)

Phase 9 connects verified candidates into the automated Strategy Tester backtesting pipeline:

```
CAND-XXXX
    ↓
Candidate Pre-flight Verification (source, binary .ex5, hashes, compile status)
    ↓
Dataset Period Resolution (research_periods.json)
    ↓
Port 3000 Conflict Check
    ↓
Candidate Binary Isolation (staged into MQL5/Experts/Candidates/CAND-XXXX.ex5)
    ↓
MT5 Strategy Tester Execution (with timeout monitoring)
    ↓
Report Verification & Anti-Contamination Identity Check
    ↓
Report Parsing & Metric Extraction (scripts/parser.py)
    ↓
Experiment Archival (experiments/EXP-XXXX/ with complete candidate provenance)
    ↓
Manifest Rebuild (experiments/manifest.json)
```

### 1. Candidate Provenance & Anti-Contamination
Every experiment created links permanently to its upstream lineage:
- `candidate_id` (`CAND-XXXX`)
- `plan_id` (`PLAN-XXXX`)
- `hypothesis_id` (`HYP-XXXX`)
- `baseline_experiment` (`EXP-XXXX`)
- Cryptographic SHA-256 hashes of `source_after.mq5` and `source_after.ex5`
- Tester synchronization audit record

### 2. Candidate Isolation Architecture
To prevent stale binary contamination or accidental execution of baseline EAs:
- Candidate binary is staged into an isolated MT5 directory: `MQL5/Experts/Candidates/{candidate_id}.ex5`.
- Strategy Tester configuration explicitly sets `Expert=Candidates\{candidate_id}.ex5`.
- Canonical EAs in `ea/` and `MQL5/Experts/` are never overwritten.
- Destination hash is verified against candidate source hash prior to MT5 launch.

### 3. Report Identity & Zero-Data vs Zero-Trade Validation
- Anti-contamination check: parses HTML report to verify the tested expert strictly matches `{candidate_id}`.
- Zero-Trade vs Zero-Data distinction:
  - If `bars > 0` and `ticks > 0`, the test is **VALID** even if `trades == 0`.
  - If `bars == 0` and `ticks == 0`, Strategy Tester failed to bind/process data (`REPORT_INVALID`).

---

## AI Auditor Architecture (Phase 10)

The AI Auditor is the evidence evaluation layer in the AI-EA-Lab quantitative research pipeline. It evaluates whether backtest outcomes and candidate execution provide valid, reproducible, and plan-compliant empirical evidence.

```
audits/
├── AUD-0001.json                  # Immutable centralized audit records
└── AUD-0002.json
experiments/EXP-XXXX/
└── audit.json                     # Colocated experiment audit copy
```

### 1. Nine Evaluation Dimensions
1. **Experiment Identity & Provenance**: Verifies unbroken lineage (`HYP -> PLAN -> CAND -> EXP`).
2. **Artifact Integrity**: Recomputes SHA-256 hashes of candidate source, binaries, and staged files.
3. **MT5 Strategy Tester Execution**: Validates that bars and ticks were processed (`bars > 0`, `ticks > 0`). Distinguishes zero-trades from zero-data.
4. **Report Consistency**: Cross-checks symbol, timeframe, date range, and metrics across metadata, metrics, and raw HTML report.
5. **Plan Compliance**: Ensures actual test parameters match the approved plan.
6. **Change Scope**: Verifies candidate MQL5 source code only modified authorized input parameters.
7. **Dataset Partitioning**: Validates training, validation, or unseen partitions (or flags unconfigured states).
8. **Overfitting & Leakage Risks**: Identifies methodological risks in testing and evaluation.
9. **Reproducibility**: Confirms that independent researchers could recreate the experiment exactly.

### 2. Evidence Grading & Separation of Concerns
- **Infrastructure Evidence vs Trading Performance Evidence**: An experiment with 0 trades can provide `STRONG` infrastructure evidence (valid MT5 run, correct compiler, verified hashes), while providing `INSUFFICIENT` trading performance evidence.
- **Fact vs Interpretation vs Risk Separation**:
  - `observations`: Empirical facts recorded by the tester and system.
  - `interpretations`: Analytical deductions derived from evidence.
  - `risks`: Methodological vulnerabilities (e.g. repeated window testing, unconfigured partitions).
- **Prohibited Terminology & Ranking Prevention**:
  The Auditor strictly enforces that no composite scoreboards, leaderboards, or declarations of "winner" or "best" are created.

---

## Research Orchestrator & Autonomous Pipeline (Phases 11–18)

The top-level Research Orchestrator (`scripts/research_orchestrator.py`) unifies the laboratory into an auditable, crash-recoverable state machine across 24 explicit states.

Key Capabilities:
- **Phase 11**: Controlled Autonomous Research Loop (`scripts/research_loop.py`) connecting all stages.
- **Phase 12**: Research dataset partitioning configuration (`config/research_periods.json`).
- **Phase 13**: Dataset-aware execution rejecting unconfigured, ambiguous, or out-of-bounds dates.
- **Phase 14**: Training → Validation pipeline with explicit approval and non-overlap guarantees.
- **Phase 15**: Reproducibility layer (`scripts/reproducibility.py`) with configuration and identity fingerprinting.
- **Phase 16**: Research Memory (`scripts/memory.py`) with idempotent observation ingestion.
- **Phase 17**: Stateful Research Orchestrator (`scripts/research_orchestrator.py`) with event logging and crash recovery.
- **Phase 18**: Final system validation, release readiness, and full failure matrix verification.

---

## Running the Automated Test Suite

Run the full automated test suite (210 unit and integration tests across 12 modules):

```bash
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

All 210 tests pass deterministically with zero failures, zero errors, and zero skips.

---

## Operational Boundaries & Non-Goals

The system strictly enforces the following hard boundaries:
- **NO Live Trading**: No broker order execution or real balance risk.
- **NO Strategy Ranking**: No leaderboards, composite scoreboards, or "winner" declarations.
- **NO Unrestricted Optimization**: No brute-force or genetic parameter sweeps.
- **NO Automatic Deployment**: EAs are never automatically deployed to live charts.
- **NO Automatic UNSEEN Access**: UNSEEN partition cannot be accessed without explicit override.
- **MANDATORY Human Approval**: Candidate code generation and backtesting require explicit authorization.
