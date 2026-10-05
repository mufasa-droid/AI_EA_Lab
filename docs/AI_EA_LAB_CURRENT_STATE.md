# AI-EA-Lab: Current Operational State & Research Summary

## What is AI-EA-Lab?
**AI-EA-Lab** is an automated quantitative research and backtesting laboratory for MetaTrader 5 (MT5). It is designed to evaluate trading strategies scientifically, preventing the data snooping, curve-fitting, and accidental errors common in manual development. 

The lab does **not** trade live money. It strictly operates as an offline research laboratory using MT5 Strategy Tester against frozen historical market datasets.

---

## How Does the System Work?
The laboratory enforces a strict unidirectional pipeline where each stage must be verified before moving to the next:

1. **AI Researcher**: Formulates a testable research hypothesis from verified facts (e.g., *"Lowering swing size on AUDUSD will increase trade opportunity"*).
2. **Experiment Planner**: Converts the hypothesis into an experiment plan with a strict baseline comparison, changing only **one parameter at a time**.
3. **Human Approval**: The system pauses. A human must explicitly approve the plan before any code can be modified or tested.
4. **AI Developer**: Takes the approved plan, applies the parameter changes inside an isolated candidate workspace, verifies the source diff, and compiles the `.ex5` binary using MetaEditor.
5. **AI Backtest Runner**: Takes the compiled candidate, resolves the correct frozen dataset partition, runs headless MT5 Strategy Tester, and extracts a verified UTF-16 HTML report.
6. **AI Auditor**: Forensically checks the report, recalculates cryptographic hashes, checks that the backtest complied with the original plan, and issues an audit certificate (`PASS`, `NEEDS_REVIEW`, or `INVALID`).
7. **Research Memory**: Indexes findings into a cumulative knowledge base so future research builds on past discoveries.

---

## Where Does the Project Stand Today?

### 1. Research Infrastructure (Phases 1–18): COMPLETE & VERIFIED
- **Test Suite**: All **210 automated unit and integration tests** pass cleanly.
- **Real MT5 Executions**: All **57 experiments** in the archive ran against real MetaTrader 5 on `Deriv-Demo` with verified bar and tick data.
- **Historical Immutability**: Cryptographic checks prove that historical experiment records have never been altered or overwritten.
- **Security**: Zero API keys, passwords, or broker credentials exist in the codebase.

### 2. The Active Strategy: `Fibonacci_EA_v5_0`
The primary Expert Advisor under evaluation is a multi-timeframe swing trading system:
- **Swing Detection**: Scans H1 fractal highs and lows (5-bar structure).
- **Entry Trigger**: Enters on M30 when price retraces into the 61.8% Fibonacci "Golden Pocket" with RSI momentum and MACD histogram confirmation.
- **Trade Management**: Closes position at Take Profit 1 (15 pips) with optional ATR volatility filter.
- **Multi-Symbol Safety**: Uses a polynomial rolling hash of the symbol name to generate unique magic numbers, allowing concurrent execution across multiple pairs without ticket collisions.

---

## What Do the Backtests Prove?

### Validated Champions: GBPUSD & EURUSD (2020–2025)
- **GBPUSD M30 (`EXP-0034` / `EXP-0035`)**:
  - *5-Year Training (2020–2024)*: **+$663.45**, Profit Factor **3.20**, Win Rate **78.1%**, Max Drawdown **3.52%**.
  - *1-Year Validation (2025)*: **+$637.23**, Profit Factor **2.29**, Win Rate **81.3%**, Max Drawdown **3.93%**.
  - *Historical Verdict*: Solid out-of-sample generalization across 2020–2025.
- **EURUSD M30 (`EXP-0036` / `EXP-0037`)**:
  - *5-Year Training (2020–2024)*: **+$548.41**, Profit Factor **1.62**, Win Rate **69.0%**, Max Drawdown **4.71%**.
  - *1-Year Validation (2025)*: **+$585.63**, Profit Factor **1.44**, Win Rate **66.7%**, Max Drawdown **5.58%**.
  - *Historical Verdict*: Stable performance across 2020–2025.

### Critical Finding: The 2026 UNSEEN Stress Benchmark & Progression
When benchmarked against the untouched 2026 UNSEEN partition (`2026.01.01` to `2026.09.30`), unmanaged champions broke down:
- **Baseline 2026 (`EXP-0048` GBPUSD / `EXP-0049` EURUSD)**: Combined loss **-$922.88**, combined drawdown **15.03%** (breached 8% limit, 81.8% Monte Carlo failure probability).
- **Target Expansion (`CAND-0030`, `EXP-0051`)**: Widening TP1 to 22 pips starved the EA and collapsed win rate to **18.75%** (**DECISIVELY FALSIFIED**).
- **ATR Volatility Filter (`CAND-0031`, `EXP-0053`)**: Filtering spike volatility brought balance drawdown down to **7.57%** (passed 8% limit).
- **TP1 75% Scale-Out (`CAND-0032`, `EXP-0055`)**: Net -$535.70, failed to close the runner drag gap.
- **1:1 Target Equalization (`CAND-0033`, `EXP-0057`)**: Setting `InpTP2Pips=15.0` restored true 1:1 risk-reward ($97 win vs $99 loss) on 32 pure market entries, achieving the best net 2026 result (**-$433.13**) with balance drawdown at **7.69%** (under 8% threshold).


### Challenging Pairs: USDJPY & AUDUSD
- **USDJPY M30 (`EXP-0038`, `EXP-0046`, `EXP-0047`)**:
  - Training profitable (+`$566.28`, PF 1.44), but failed 2025 validation (`-$804.63`, PF 0.18) due to BoJ monetary policy regime shifts.
- **AUDUSD M30 (`EXP-0040`–`EXP-0044`)**:
  - 1:3 payout asymmetry caused heavy training drag (`-$800.31` to `-$860.89`), though 2025 validation rebounded (`+$240.82`, PF 1.78).

---

## Separating Facts from Myths

| Claim | Reality Based on Evidence |
| :--- | :--- |
| *"The EA is ready to go live or trade prop firm challenge."* | **DEFINITIVELY FALSE.** Deploying into 2026 market conditions carries an 81.8%–94.6% statistical probability of account liquidation / drawdown breach. |
| *"The EA makes 4–6 trades per week."* | **False.** The EA averages 15–25 trades per year per pair (~0.3 trades/week). It is a patient swing system, not a scalper. |
| *"The EA will pass an 8–10% prop firm challenge in 4 weeks."* | **False.** Average monthly returns are ~1.0% to 1.5% at 1% risk. Attempting 10% in 4 weeks would require excessive leverage that risks account wipeout. |
| *"The system is deployed on AWS with Telegram alerts."* | **False.** No AWS infrastructure, Telegram bots, or Discord webhooks exist. Only a local console monitor exists. |

---

## What Should Happen Next?

**The EA must NOT be deployed live under current parameters.**

**Next Research Action:**
1. **Regime Adaptation Hypothesis**: Formulate and test a dynamic volatility/regime filter (e.g. ATR-normalized take-profit / stop-loss ratios) to eliminate the 1:3 payout asymmetry that caused the 2026 drawdown.
2. **Re-test 2026 Recovery**: Re-evaluate candidates against the 2026 partition until drawdown remains strictly under 5.0% and profit factor exceeds 1.50 across all partitions.
3. **Controlled Live Demo**: Only after 2026 robustness is proven should forward demo monitoring begin.
