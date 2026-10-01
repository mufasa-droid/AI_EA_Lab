# AI-EA-Lab: Session Handoff & Continuity Guide
**Session Date:** October 2, 2026  
**State:** Clean workspace, 210 passing unit tests, synchronized with GitHub `origin/main`.

---

## 1. Verified Champion Configuration

The definitive champion architecture established across 27 laboratory experiments is:

- **EA Source**: `ea/Fibonacci_EA_v5_0.mq5` (default `InpTP1Pips = 15.0`, `InpDirection = 2`).
- **Execution Chart**: **M30 Timeframe**.
- **Direction**: Both Long & Short (`InpDirection = 2`).
- **Take Profit 1**: `15.0 pips` (50% partial close + move to Breakeven).
- **Take Profit 2**: `30.0 pips` (trailing runner).
- **Stop Loss**: `15.0 pips` hard stop.
- **Risk**: `1.0%` dynamic lot sizing.
- **News Filter**: Enabled (`30 mins` buffer).

---

## 2. Multi-Market Empirical Validation (2025 Out-of-Sample)

| Instrument | Timeframe | 2025 Net Profit | Profit Factor | Win Rate | Max Drawdown | Audit |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **GBPUSD** | **M30** | **+$505.25** | **1.49** | **74.58%** | **3.88%** | `PASS` (AUD-0025) |
| **EURUSD** | **M30** | **+$535.68** | **1.62** | **74.55%** | **4.85%** | `PASS` (AUD-0029) |
| **Combined** | **M30** | **+$1,040.93** | **1.55** | **74.57%** | **<5.0%** | **Both Pass** |

---

## 3. Immediate Roadmap for Tomorrow

**Objective**: Configure the M30 champion to pass a **$5,000 Prop Firm Phase 1 Challenge** (+8% to +10% target) in **4 to 8 weeks** without exceeding a 5%–6% drawdown.

1. **Multi-Pair Portfolio Testing**:
   - Backtest **AUDUSD M30** and **USDJPY M30** to establish a 4-pair uncorrelated basket.
   - Increases execution frequency from ~1 trade/week to **~4–5 trades/week** (~16–20 trades/month).
2. **Soft Lot Sizing Evaluation**:
   - Test disabling `InpUseH4Soft` and `InpUseAdxSoft` so winning trades yield the full $35–$60 rather than throttled $18–$30.
3. **Runner Optimization**:
   - Test expanding `InpTP2Pips` from 30 to 45–50 pips on the risk-free runner.
4. **MT5 Live Demo Staging**:
   - Prepare configuration files and instructions for running on an MT5 demo account.

---

## 4. Environment & Repository Status
- Git commit: `a5e51c1` (ahead commit: `269f826`).
- All 210 unit tests passing.
- 27 experiments recorded in `experiments/manifest.json`.
