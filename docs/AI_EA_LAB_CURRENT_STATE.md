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
- **Real MT5 Executions**: All **41 experiments** in the archive ran against real MetaTrader 5 on `Deriv-Demo` with verified bar and tick data.
- **Historical Immutability**: Cryptographic checks prove that historical experiment records have never been altered or overwritten.
- **Security**: Zero API keys, passwords, or broker credentials exist in the codebase.

### 2. The Active Strategy: `Fibonacci_EA_v5_0`
The primary Expert Advisor under evaluation is a multi-timeframe swing trading system:
- **Swing Detection**: Scans H1 fractal highs and lows (5-bar structure).
- **Entry Trigger**: Enters on M30 when price retraces into the 61.8% Fibonacci "Golden Pocket" with RSI momentum and MACD histogram confirmation.
- **Trade Management**: Closes 50% of the position at Take Profit 1 (e.g. 15 pips), moves the stop loss to break-even, and trails the remaining 50% volume.
- **Multi-Symbol Safety**: Uses a polynomial rolling hash of the symbol name to generate unique magic numbers, allowing concurrent execution across multiple pairs without ticket collisions.

---

## What Do the Backtests Prove?

### Validated Champions: GBPUSD & EURUSD
- **GBPUSD M30 (`EXP-0034` / `EXP-0035`)**:
  - *5-Year Training (2020–2024)*: **+$663.45**, Profit Factor **3.20**, Win Rate **78.1%**, Max Drawdown **3.52%**.
  - *1-Year Validation (2025)*: **+$637.23**, Profit Factor **2.29**, Win Rate **81.3%**, Max Drawdown **3.93%**.
  - *Verdict*: Highly robust out-of-sample generalization.
- **EURUSD M30 (`EXP-0036` / `EXP-0037`)**:
  - *5-Year Training (2020–2024)*: **+$548.41**, Profit Factor **1.62**, Win Rate **69.0%**, Max Drawdown **4.71%**.
  - *1-Year Validation (2025)*: **+$585.63**, Profit Factor **1.44**, Win Rate **66.7%**, Max Drawdown **5.58%**.
  - *Verdict*: Solid, stable performance across both training and unseen validation.

### Challenging Pairs: USDJPY & AUDUSD
- **USDJPY M30 (`EXP-0038` / `EXP-0039`)**:
  - Enabling the Asian session made training profitable (**+$514.80**, PF 1.35), but it failed 2025 validation (**-$804.63**, PF 0.52) due to sharp interest rate divergence and Bank of Japan interventions.
- **AUDUSD M30 (`EXP-0040` / `EXP-0041`)**:
  - Narrowing the swing filter generated 68 trades with a 66.2% win rate, but training lost money (**-$800.31**) due to a payout asymmetry: banking 50% profit at 15 pips while absorbing full 15-pip losses during a multi-year USD downtrend. In 2025 validation, however, it rebounded strongly (**+$240.82**, PF 1.78, 82.4% win rate).

---

## Separating Facts from Myths

| Claim | Reality Based on Evidence |
| :--- | :--- |
| *"The EA makes 4–6 trades per week."* | **False.** The EA averages 15–25 trades per year per pair (~0.3 trades/week). It is a patient swing system, not a scalper. |
| *"The EA will pass an 8–10% prop firm challenge in 4 weeks."* | **False.** Average monthly returns are ~1.0% to 1.5% at 1% risk. Attempting 10% in 4 weeks would require excessive leverage that risks account wipeout. |
| *"The system is deployed on AWS with Telegram alerts."* | **False.** No AWS infrastructure, Telegram bots, or Discord webhooks exist. Only a local console monitor exists. |
| *"Auto-Profile is implemented."* | **False.** Auto-Profile is only a proposal. Parameters are currently managed via individual `.set` preset files. |

---

## What Should Happen Next?

**Do not build more infrastructure.** The laboratory platform is complete and working.

**Recommended Next Step:**
1. **Calibrate AUDUSD**: Test increasing TP1 from 15 pips to 20–22 pips to eliminate the 1:3 payout asymmetry and reward runners.
2. **Calibrate USDJPY**: Test an ATR volatility filter to protect the EA during central bank rate shocks.
3. **Maintain Separate `.set` Presets**: Avoid hardcoding complex profile-switching code into the EA. Keep currency-specific parameters in auditable `.set` files.
4. **Prepare Forward Evaluation**: Once AUDUSD and USDJPY are calibrated, benchmark the combined multi-pair portfolio against the frozen 2026 UNSEEN dataset before considering live demo forwarding.
