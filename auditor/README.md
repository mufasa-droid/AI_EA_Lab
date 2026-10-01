 # AI Auditor (Phase 10)

The AI Auditor is the evidence evaluation layer in the AI-EA-Lab quantitative research pipeline.

```
AI Researcher -> Experiment Planner -> Human Approval -> AI Developer -> MT5 Strategy Tester -> AI Auditor
```

## Role & Boundaries

The Auditor evaluates whether an experiment's evidence is:
- **Valid**: Free of data contamination, zero-data failures, or corrupt records.
- **Internally Consistent**: Cross-references between metadata, metrics, and report match without contradictions.
- **Reproducible**: All source code, binaries, tester configs, and cryptographic hashes are preserved.
- **Plan-Compliant**: Backtest parameters strictly honor the human-approved Experiment Plan.
- **Methodologically Sound**: Evaluates risks of overfitting, data leakage, and lack of robustness.

### Strict Non-Goals
The Auditor is **NOT**:
- An optimizer or parameter sweeper.
- A ranking engine or leaderboard.
- A trading advisor.
- Allowed to designate any EA as "Winner", "Best", or "Optimal".
- Allowed to produce numerical scores out of 100.

## Evaluation Dimensions

1. **Experiment Identity & Provenance**: Verifies unbroken lineage `HYP -> PLAN -> CAND -> EXP`.
2. **Artifact Integrity**: Recomputes SHA-256 hashes of candidate source, binaries, and staged files.
3. **MT5 Strategy Tester Execution**: Validates that bars and ticks were processed (`bars > 0`, `ticks > 0`). Distinguishes zero-trades from zero-data.
4. **Report Consistency**: Cross-checks symbol, timeframe, date range, and metrics across all experiment files.
5. **Plan Compliance**: Ensures actual test parameters match the approved plan.
6. **Change Scope**: Verifies candidate MQL5 source code only modified authorized input parameters.
7. **Dataset Partitioning**: Validates training, validation, or unseen partitions (or flags unconfigured states).
8. **Overfitting & Leakage Risks**: Identifies methodological risks in testing and evaluation.
9. **Reproducibility**: Confirms that independent researchers could recreate the experiment exactly.

## Output Artifacts

Audits are saved as immutable structured records:
- `experiments/EXP-XXXX/audit.json`: Colocated with the experiment.
- `audits/AUD-XXXX.json`: Centrally archived by audit identifier.
