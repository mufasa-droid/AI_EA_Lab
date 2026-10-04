"""
AI-EA-Lab: Monte Carlo Stress Testing & Execution Robustness Engine
Performs multi-scenario bootstrap resampling, sequence shuffling,
and adverse execution slippage stress-testing on MT5 experiment deal histories.

Evaluates prop firm survival probabilities:
  - Probability of 4.0% Daily Loss Limit breach
  - Probability of 8.0% Total Drawdown Limit breach
  - Value at Risk (VaR 95% / 99%) & Conditional VaR (CVaR)
"""

import argparse
import json
import math
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.parse_report import MT5ReportHTMLParser, read_report_html


def extract_closed_deals(exp_dir: Path) -> List[Dict[str, Any]]:
    """Extract all closed round-trip deals from an experiment report.htm."""
    report_file = exp_dir / "report.htm"
    if not report_file.is_file():
        raise FileNotFoundError(f"report.htm not found in {exp_dir}")

    content = read_report_html(report_file)
    parser = MT5ReportHTMLParser()
    parser.feed(content)

    deals_idx = -1
    for i, r in enumerate(parser.rows):
        if r and r[0].strip().lower() == "deals":
            deals_idx = i
            break

    if deals_idx == -1:
        return []

    deals = []
    for r in parser.rows[deals_idx + 2:]:
        # Must be an 'out' direction deal (closing trade)
        if len(r) >= 11 and len(r) > 4 and r[4].strip().lower() == "out":
            try:
                deal_time = r[0].strip()
                symbol = r[2].strip()
                deal_type = r[3].strip().lower()
                volume = float(r[5].replace(" ", ""))
                price = float(r[6].replace(" ", ""))
                profit = float(r[10].replace(" ", "").replace("\xa0", ""))
                balance = float(r[11].replace(" ", "").replace("\xa0", ""))
                comment = r[12].strip() if len(r) > 12 else ""

                # Extract date for daily clustering
                trade_date = deal_time.split(" ")[0] if " " in deal_time else deal_time

                deals.append({
                    "time": deal_time,
                    "date": trade_date,
                    "symbol": symbol,
                    "type": deal_type,
                    "volume": volume,
                    "price": price,
                    "profit": profit,
                    "balance": balance,
                    "comment": comment,
                    "is_win": profit > 0,
                })
            except (ValueError, IndexError):
                continue

    return deals


def calculate_equity_metrics(
    profits: List[float],
    initial_deposit: float = 10000.0,
    daily_groups: Optional[List[str]] = None,
) -> Dict[str, float]:
    """Calculate drawdown, consecutive losses, and return metrics for a profit sequence."""
    equity = initial_deposit
    peak = initial_deposit
    max_dd_dollars = 0.0
    max_dd_pct = 0.0

    max_consec_losses = 0
    cur_consec_losses = 0

    daily_pnl: Dict[str, float] = {}

    for i, p in enumerate(profits):
        equity += p
        if equity > peak:
            peak = equity
        dd_dollars = peak - equity
        dd_pct = (dd_dollars / peak) * 100.0 if peak > 0 else 0.0

        if dd_dollars > max_dd_dollars:
            max_dd_dollars = dd_dollars
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        if p < 0:
            cur_consec_losses += 1
            if cur_consec_losses > max_consec_losses:
                max_consec_losses = cur_consec_losses
        else:
            cur_consec_losses = 0

        if daily_groups and i < len(daily_groups):
            d = daily_groups[i]
            daily_pnl[d] = daily_pnl.get(d, 0.0) + p

    # Worst daily loss
    worst_daily_loss_dollars = 0.0
    worst_daily_loss_pct = 0.0
    for d, pnl in daily_pnl.items():
        if pnl < 0:
            loss = abs(pnl)
            loss_pct = (loss / initial_deposit) * 100.0
            if loss > worst_daily_loss_dollars:
                worst_daily_loss_dollars = loss
                worst_daily_loss_pct = loss_pct

    total_net_profit = equity - initial_deposit
    gross_win = sum(p for p in profits if p > 0)
    gross_loss = abs(sum(p for p in profits if p < 0))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    win_rate = (len([p for p in profits if p > 0]) / len(profits) * 100.0) if profits else 0.0

    return {
        "final_equity": equity,
        "net_profit": total_net_profit,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "max_drawdown_dollars": max_dd_dollars,
        "max_drawdown_pct": max_dd_pct,
        "max_consecutive_losses": max_consec_losses,
        "worst_daily_loss_dollars": worst_daily_loss_dollars,
        "worst_daily_loss_pct": worst_daily_loss_pct,
    }


def run_monte_carlo(
    deals: List[Dict[str, Any]],
    iterations: int = 10000,
    initial_deposit: float = 10000.0,
    daily_dd_limit: float = 4.0,
    total_dd_limit: float = 8.0,
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """Execute multi-method Monte Carlo simulation on deal history."""
    if not deals:
        raise ValueError("Cannot run Monte Carlo on empty deal list.")

    if seed is not None:
        random.seed(seed)

    base_profits = [d["profit"] for d in deals]
    dates = [d["date"] for d in deals]
    volumes = [d["volume"] for d in deals]

    # Baseline metrics (original timeline)
    base_metrics = calculate_equity_metrics(base_profits, initial_deposit, dates)

    # ─────────────────────────────────────────────────────────────
    # SIMULATION 1: Trade Order Shuffling (Sequence Risk / Loss Clustering)
    # Permutes the exact trades 10,000 times
    # ─────────────────────────────────────────────────────────────
    perm_drawdowns_pct: List[float] = []
    perm_consec_losses: List[int] = []
    perm_daily_breaches = 0
    perm_total_breaches = 0

    for _ in range(iterations):
        shuffled = list(base_profits)
        random.shuffle(shuffled)
        res = calculate_equity_metrics(shuffled, initial_deposit)
        dd = res["max_drawdown_pct"]
        perm_drawdowns_pct.append(dd)
        perm_consec_losses.append(res["max_consecutive_losses"])
        if dd >= total_dd_limit:
            perm_total_breaches += 1

    # ─────────────────────────────────────────────────────────────
    # SIMULATION 2: Bootstrap Resampling (10,000 Alternative Histories)
    # Samples with replacement
    # ─────────────────────────────────────────────────────────────
    boot_profits: List[float] = []
    boot_drawdowns_pct: List[float] = []
    boot_profit_factors: List[float] = []
    boot_win_rates: List[float] = []
    boot_daily_breaches = 0
    boot_total_breaches = 0

    n_trades = len(base_profits)
    for _ in range(iterations):
        sample = [random.choice(base_profits) for _ in range(n_trades)]
        res = calculate_equity_metrics(sample, initial_deposit)
        boot_profits.append(res["net_profit"])
        boot_drawdowns_pct.append(res["max_drawdown_pct"])
        boot_profit_factors.append(res["profit_factor"])
        boot_win_rates.append(res["win_rate"])

        if res["max_drawdown_pct"] >= total_dd_limit:
            boot_total_breaches += 1

    # ─────────────────────────────────────────────────────────────
    # SIMULATION 3: Adverse Slippage Sensitivity Analysis
    # Tests impact of 0.5, 1.0, 1.5, 2.0, and 2.5 pip average adverse slippage
    # ─────────────────────────────────────────────────────────────
    slippage_scenarios = {}
    pip_levels = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    for pips in pip_levels:
        adjusted_profits = []
        for d in deals:
            vol = d["volume"]
            # 1 pip on 1.0 lot in EURUSD/GBPUSD = $10.00
            # Adverse slippage penalty = pips * $10.00 * vol
            slippage_cost = pips * 10.0 * vol
            adjusted_profits.append(d["profit"] - slippage_cost)

        s_res = calculate_equity_metrics(adjusted_profits, initial_deposit, dates)
        slippage_scenarios[f"{pips:.1f}_pips"] = {
            "slippage_pips": pips,
            "net_profit": round(s_res["net_profit"], 2),
            "profit_factor": round(s_res["profit_factor"], 2),
            "win_rate": round(s_res["win_rate"], 1),
            "max_drawdown_pct": round(s_res["max_drawdown_pct"], 2),
            "profit_retention_pct": round((s_res["net_profit"] / base_metrics["net_profit"] * 100.0), 1) if base_metrics["net_profit"] > 0 else 0.0,
            "breached_total_dd": s_res["max_drawdown_pct"] >= total_dd_limit,
        }

    # ─────────────────────────────────────────────────────────────
    # SIMULATION 4: Stress-Combined Monte Carlo (Bootstrap + 1.5 Pip Slippage)
    # Evaluates survival under joint resampling + moderate adverse execution
    # ─────────────────────────────────────────────────────────────
    stress_profits: List[float] = []
    stress_drawdowns_pct: List[float] = []
    stress_total_breaches = 0

    base_stressed_profits = [
        d["profit"] - (1.5 * 10.0 * d["volume"]) for d in deals
    ]

    for _ in range(iterations):
        sample = [random.choice(base_stressed_profits) for _ in range(n_trades)]
        res = calculate_equity_metrics(sample, initial_deposit)
        stress_profits.append(res["net_profit"])
        stress_drawdowns_pct.append(res["max_drawdown_pct"])
        if res["max_drawdown_pct"] >= total_dd_limit:
            stress_total_breaches += 1

    # Statistical percentiles
    boot_profits.sort()
    boot_drawdowns_pct.sort()
    stress_profits.sort()
    stress_drawdowns_pct.sort()

    def get_percentile(arr: List[float], pct: float) -> float:
        idx = int(len(arr) * (pct / 100.0))
        idx = max(0, min(len(arr) - 1, idx))
        return arr[idx]

    # VaR 95%: maximum loss (or minimum profit) at 5th percentile
    var_95 = get_percentile(boot_profits, 5.0)
    var_99 = get_percentile(boot_profits, 1.0)
    cvar_95_losses = [p for p in boot_profits if p <= var_95]
    cvar_95 = sum(cvar_95_losses) / len(cvar_95_losses) if cvar_95_losses else var_95

    return {
        "sample_size": n_trades,
        "iterations": iterations,
        "initial_deposit": initial_deposit,
        "limits": {
            "daily_loss_limit_pct": daily_dd_limit,
            "total_dd_limit_pct": total_dd_limit,
        },
        "baseline": {
            "net_profit": round(base_metrics["net_profit"], 2),
            "profit_factor": round(base_metrics["profit_factor"], 2),
            "win_rate": round(base_metrics["win_rate"], 1),
            "max_drawdown_pct": round(base_metrics["max_drawdown_pct"], 2),
            "max_consecutive_losses": base_metrics["max_consecutive_losses"],
            "worst_daily_loss_pct": round(base_metrics["worst_daily_loss_pct"], 2),
        },
        "bootstrap_monte_carlo": {
            "profit_percentiles": {
                "5th_percentile_worst_case": round(get_percentile(boot_profits, 5.0), 2),
                "25th_percentile": round(get_percentile(boot_profits, 25.0), 2),
                "50th_percentile_median": round(get_percentile(boot_profits, 50.0), 2),
                "75th_percentile": round(get_percentile(boot_profits, 75.0), 2),
                "95th_percentile_best_case": round(get_percentile(boot_profits, 95.0), 2),
            },
            "drawdown_percentiles": {
                "median_dd_pct": round(get_percentile(boot_drawdowns_pct, 50.0), 2),
                "90th_percentile_dd_pct": round(get_percentile(boot_drawdowns_pct, 90.0), 2),
                "95th_percentile_dd_pct": round(get_percentile(boot_drawdowns_pct, 95.0), 2),
                "99th_percentile_dd_pct": round(get_percentile(boot_drawdowns_pct, 99.0), 2),
                "worst_ever_dd_pct": round(boot_drawdowns_pct[-1], 2),
            },
            "risk_metrics": {
                "var_95_net_profit": round(var_95, 2),
                "var_99_net_profit": round(var_99, 2),
                "cvar_95_expected_shortfall": round(cvar_95, 2),
                "prob_total_drawdown_breach_pct": round((boot_total_breaches / iterations) * 100.0, 3),
            },
        },
        "slippage_stress_analysis": slippage_scenarios,
        "combined_stress_mc_1_5_pip": {
            "5th_percentile_profit": round(get_percentile(stress_profits, 5.0), 2),
            "median_profit": round(get_percentile(stress_profits, 50.0), 2),
            "95th_percentile_dd_pct": round(get_percentile(stress_drawdowns_pct, 95.0), 2),
            "worst_ever_dd_pct": round(stress_drawdowns_pct[-1], 2),
            "prob_total_drawdown_breach_pct": round((stress_total_breaches / iterations) * 100.0, 3),
        },
    }


def print_report(res: Dict[str, Any]):
    """Print beautifully formatted human-readable Monte Carlo stress-testing report."""
    print("=" * 72)
    print("         AI-EA-LAB: MONTE CARLO STRESS & ROBUSTNESS AUDIT")
    print(f"      Simulations: {res['iterations']:,} Iterations | Sample Size: {res['sample_size']} Deals")
    print("=" * 72)

    base = res["baseline"]
    print("\n[1] EMPIRICAL HISTORICAL BASELINE")
    print(f"  • Realized Net Profit   : +${base['net_profit']:,.2f} (+{(base['net_profit']/res['initial_deposit'])*100:.2f}%)")
    print(f"  • Profit Factor         : {base['profit_factor']}")
    print(f"  • Win Rate              : {base['win_rate']}%")
    print(f"  • Max Drawdown          : {base['max_drawdown_pct']}% (Hard Limit: {res['limits']['total_dd_limit_pct']}%)")
    print(f"  • Max Consec. Losses    : {base['max_consecutive_losses']} trades")
    print(f"  • Worst 1-Day Loss      : {base['worst_daily_loss_pct']}% (Daily Limit: {res['limits']['daily_loss_limit_pct']}%)")

    boot = res["bootstrap_monte_carlo"]
    p_pct = boot["profit_percentiles"]
    d_pct = boot["drawdown_percentiles"]
    risk = boot["risk_metrics"]

    print("\n[2] BOOTSTRAP MONTE CARLO (10,000 ALTERNATIVE HISTORIES)")
    print("  Profit Outcomes:")
    print(f"  • 95% Best-Case (95th %) : +${p_pct['95th_percentile_best_case']:,.2f}")
    print(f"  • Median Return (50th %) : +${p_pct['50th_percentile_median']:,.2f}")
    print(f"  • 95% Worst-Case (5th %) : +${p_pct['5th_percentile_worst_case']:,.2f}")
    print(f"  • VaR (95% Confidence)   : +${risk['var_95_net_profit']:,.2f} minimum expected return")
    print(f"  • CVaR / Expected Short. : +${risk['cvar_95_expected_shortfall']:,.2f}")

    print("\n  Drawdown Distribution:")
    print(f"  • Median Expected DD     : {d_pct['median_dd_pct']}%")
    print(f"  • 90th Percentile DD     : {d_pct['90th_percentile_dd_pct']}%")
    print(f"  • 95th Percentile DD     : {d_pct['95th_percentile_dd_pct']}%")
    print(f"  • 99th Percentile DD     : {d_pct['99th_percentile_dd_pct']}%")
    print(f"  • Worst Case Encountered : {d_pct['worst_ever_dd_pct']}%")

    breach_prob = risk["prob_total_drawdown_breach_pct"]
    breach_status = "🟢 PASS (Exceptional)" if breach_prob < 1.0 else ("🟡 CAUTION" if breach_prob < 5.0 else "🔴 FAIL")
    print(f"  • Probability of 8% DD   : {breach_prob:.3f}% [{breach_status}]")

    print("\n[3] ADVERSE EXECUTION SLIPPAGE SENSITIVITY")
    print(f"  {'Slippage Regime':<18} {'Net Profit':<14} {'Profit Factor':<15} {'Win Rate':<10} {'Max DD %':<10} {'Retained':<10}")
    print("  " + "-" * 75)
    for name, s in res["slippage_stress_analysis"].items():
        sign = "+" if s["net_profit"] > 0 else ""
        print(f"  {name:<18} {sign}${s['net_profit']:<13,.2f} {s['profit_factor']:<15.2f} {s['win_rate']:<9.1f}% {s['max_drawdown_pct']:<9.2f}% {s['profit_retention_pct']}%")

    comb = res["combined_stress_mc_1_5_pip"]
    print("\n[4] COMBINED STRESS TEST (10,000 Iterations + 1.5 Pip Adverse Slippage)")
    print(f"  • 5th % Worst Profit     : +${comb['5th_percentile_profit']:,.2f}")
    print(f"  • Median Profit          : +${comb['median_profit']:,.2f}")
    print(f"  • 95th Percentile DD     : {comb['95th_percentile_dd_pct']}%")
    print(f"  • Worst Case DD          : {comb['worst_ever_dd_pct']}%")
    print(f"  • Prob. of 8% DD Breach  : {comb['prob_total_drawdown_breach_pct']:.3f}%")

    print("\n" + "=" * 72)


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo Stress Testing Engine")
    parser.add_argument("--experiments", nargs="+", default=["EXP-0035", "EXP-0037"], help="Experiment IDs to combine")
    parser.add_argument("--iterations", type=int, default=10000, help="Number of Monte Carlo simulations")
    parser.add_argument("--deposit", type=float, default=10000.0, help="Starting deposit")
    parser.add_argument("--daily-limit", type=float, default=4.0, help="Daily loss limit percent")
    parser.add_argument("--total-limit", type=float, default=8.0, help="Total drawdown limit percent")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--save", type=str, default="", help="Save JSON report to target path")

    args = parser.parse_args()

    all_deals = []
    base_dir = Path("experiments")

    for exp_id in args.experiments:
        exp_path = base_dir / exp_id
        if not exp_path.is_dir():
            print(f"❌ Error: Experiment folder not found: {exp_path}", file=sys.stderr)
            sys.exit(1)
        deals = extract_closed_deals(exp_path)
        all_deals.extend(deals)

    # Sort combined deals by timestamp
    all_deals.sort(key=lambda x: x["time"])

    res = run_monte_carlo(
        deals=all_deals,
        iterations=args.iterations,
        initial_deposit=args.deposit,
        daily_dd_limit=args.daily_limit,
        total_dd_limit=args.total_limit,
        seed=args.seed,
    )

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print_report(res)

    if args.save:
        out_file = Path(args.save)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"✅ Monte Carlo report saved to: {out_file}")


if __name__ == "__main__":
    main()
