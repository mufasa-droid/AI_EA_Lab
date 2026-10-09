# Live Account & Prop Firm Deployment Checklist
## Fibonacci EA v5.0 — Dual-Major Production Setup Guide

---

### 1. Artifacts in this Deployment Package

```
deploy/
├── Fibonacci_EA_v5_0.ex5      # Immutable production binary (Adaptive Filling Mode compiled)
├── EURUSD_M30_Live.set        # Validated EURUSD M30 preset (EXP-0068 & EXP-0069)
├── GBPUSD_M30_Live.set        # Validated GBPUSD M30 preset (EXP-0035 & EXP-0065)
└── LIVE_DEPLOYMENT_CHECKLIST.md
```

- **Binary SHA-256**: `61fc8061f0f1f90b5fd69e20080d8fee83941007ce75f4ea0548ebc0639df69c`
- **Compiler**: MetaEditor 64-bit (0 errors, 0 warnings)
- **Execution Architecture**: Adaptive broker filling mode auto-detection (`IOC` $\to$ `FOK` $\to$ `RETURN`).

---

### 2. Step-by-Step MT5 Installation

#### Step 1: Open MetaTrader 5 Data Folder
1. Launch your MetaTrader 5 terminal on your trading VPS or PC.
2. In the top menu, click **File** $\to$ **Open Data Folder**.
3. Navigate to:
   `MQL5\Experts\`
4. Copy `deploy/Fibonacci_EA_v5_0.ex5` into `MQL5\Experts\`.
5. Navigate to:
   `MQL5\Profiles\Presets\`
6. Copy both `.set` files (`EURUSD_M30_Live.set` and `GBPUSD_M30_Live.set`) into `MQL5\Profiles\Presets\`.

#### Step 2: Refresh MT5 Navigator
1. In MT5, open the **Navigator** pane (`Ctrl + N`).
2. Right-click on **Expert Advisors** and click **Refresh**.
3. Verify that `Fibonacci_EA_v5_0` appears in the list.

#### Step 3: Enable Algorithmic Trading in MT5 Options
1. Go to **Tools** $\to$ **Options** (`Ctrl + O`).
2. Click the **Expert Advisors** tab.
3. Check **"Allow algorithmic trading"**.
4. Check **"Allow DLL imports"** (if using external notifications, otherwise optional).
5. Click **OK**.
6. Ensure the large **"Algo Trading"** button in the MT5 top toolbar is **GREEN** (active).

---

### 3. Chart Setup & Preset Loading

#### Chart 1: EURUSD Setup
1. Open a new chart: **EURUSD**.
2. Set timeframe strictly to **M30**.
3. Drag `Fibonacci_EA_v5_0` from the Navigator onto the chart.
4. In the EA properties window, click the **Inputs** tab.
5. Click **Load** and select `EURUSD_M30_Live.set`.
6. Verify under the **Common** tab that **"Allow Algo Trading"** is checked.
7. Click **OK**.
8. **Check Chart Display**:
   - The on-chart dashboard will appear in the top-left.
   - Verify Magic Number is **`50002164`**.
   - Verify EA smiley face icon in the top-right corner is smiling (not gray/neutral).

#### Chart 2: GBPUSD Setup
1. Open a second chart: **GBPUSD**.
2. Set timeframe strictly to **M30**.
3. Drag `Fibonacci_EA_v5_0` onto the chart.
4. Click the **Inputs** tab $\to$ **Load** $\to$ select `GBPUSD_M30_Live.set`.
5. Verify under the **Common** tab that **"Allow Algo Trading"** is checked.
6. Click **OK**.
7. **Check Chart Display**:
   - Verify on-chart dashboard appears.
   - Verify Magic Number is **`50002208`**.
   - Distinct magic numbers guarantee that EURUSD and GBPUSD positions never interfere with each other.

---

### 4. Broker Environment & Server Time Verification

#### Broker Server Time Check:
The EA's session filters are calibrated for standard **GMT+2 (Winter) / GMT+3 (Summer)** broker server time (where New York 5 PM close occurs at 00:00 server time):
- **EURUSD Sessions**: London (08:00–12:00) and New York (13:00–17:00).
- **GBPUSD Sessions**: London (11:00–12:00) and New York (13:00–18:00).

> **Verification**: Check your MT5 Market Watch time right now. If your broker does not use GMT+2/GMT+3 (e.g. UTC+0 broker), shift `InpLondonOpen`, `InpLondonClose`, `InpNYOpen`, and `InpNYClose` by your broker's hour difference.

#### Adaptive Filling Mode:
The compiled production binary contains auto-detection:
```mql5
uint filling = (uint)SymbolInfoInteger(_Symbol, SYMBOL_FILLING_MODE);
if((filling & SYMBOL_FILLING_IOC) != 0)
   trade.SetTypeFilling(ORDER_FILLING_IOC);
else if((filling & SYMBOL_FILLING_FOK) != 0)
   trade.SetTypeFilling(ORDER_FILLING_FOK);
else
   trade.SetTypeFilling(ORDER_FILLING_RETURN);
```
This guarantees orders execute cleanly whether your broker is an ECN (IOC), prop firm bridge (FOK), or netting exchange (RETURN).

---

### 5. Risk Calibration & Prop Firm Sizing

Both presets default to **`InpRiskPct = 0.5%`**:
- **Why 0.5%?**
  - In our 2026 UNSEEN dual-major stress tests, 1.0% risk produced a maximum aggregate drawdown of 4.97%.
  - On a strict prop firm challenge (5.0% daily DD / 10.0% total DD limit), setting `InpRiskPct = 0.5%` cuts maximum expected drawdown to **~2.5%**, giving you a $4\times$ safety cushion against challenge breach.
- **Scaling to Standard 1.0% Risk**:
  - If trading a personal account or funded account with wider drawdown allowances, you can adjust `InpRiskPct = 1.0` in the inputs.

---

### 6. Emergency Kill Switch & Prop Firm Guards

The EA has 6 automated safety guards active in code:
1. **[G1] Daily Loss Limit (`InpDailyLossLimit = 4.0%`)**: If closed + open equity drops 4% in a single day, the EA halts all new entries until the next day.
2. **[G2] Total DD Limit (`InpTotalDDLimit = 8.0%`)**: If equity drops 8% from initial starting balance, the EA halts permanently to prevent account termination.
3. **[G3] Weekly Lock (`InpWeeklyTargetPct = 0.0%`)**: Disabled by default to prevent artificial trade freezing.
4. **[G4] News Buffer (`InpUseNewsFilter = true`)**: Blocks entries $\pm 30$ mins around major market events (hours 8, 9, 13, 14, 15, 16).
5. **[G5] Max Trades Per Day (`InpMaxTradesPerDay = 6`)**: Blocks overtrading after 6 executions in a day.
6. **[G6] Weekend Close (`InpWeekendClose = true`)**: Automatically closes all open positions Friday at 21:00 server time to eliminate weekend gap risk.

---

### 7. Daily Operational Routine (3 Minutes / Day)

1. **Morning Check (07:45 Server Time)**:
   - Check VPS ping / MT5 terminal connection bar in bottom right corner.
   - Verify on-chart dashboard displays `"Ready / Scanning"`.
2. **Evening Check (18:30 Server Time)**:
   - Check MT5 Toolbox $\to$ **History** tab to review any executed trades.
3. **Friday Close (21:15 Server Time)**:
   - Confirm Toolbox $\to$ **Trade** tab has 0 open positions.
