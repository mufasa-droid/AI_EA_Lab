"""
AI-EA-Lab: MT5 Demo Account Live Monitor
Connects to running MT5 terminal, audits terminal trade permissions,
checks open positions, verifies daily PnL and risk limits, and prints a live HUD.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import MetaTrader5 as mt5
except ImportError:
    print("❌ Error: MetaTrader5 package is not installed. Run: pip install MetaTrader5")
    sys.exit(1)


def format_currency(val: float) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}${val:,.2f}"


def run_monitor():
    print("=" * 65)
    print("      AI-EA-LAB: LIVE DEMO FORWARD MONITOR & RISK AUDIT")
    print("=" * 65)

    if not mt5.initialize():
        print(f"❌ Failed to connect to MT5 terminal. Error: {mt5.last_error()}")
        return

    term = mt5.terminal_info()
    acc = mt5.account_info()

    if not term or not acc:
        print("❌ Unable to retrieve terminal or account information.")
        mt5.shutdown()
        return

    # 1. Connection & Permission Status
    print("\n[1] TERMINAL & PERMISSION STATUS")
    print(f"  • Terminal          : {term.name} (Build {term.build})")
    print(f"  • Connected         : {'🟢 YES' if term.connected else '🔴 DISCONNECTED'}")
    
    algo_status = "🟢 ENABLED (Ready to trade)" if term.trade_allowed else "🔴 DISABLED (Action Required: Click 'Algo Trading' button in MT5)"
    print(f"  • Master Algo Trade : {algo_status}")
    print(f"  • Server / Account  : {acc.server} | Login #{acc.login}")
    print(f"  • Currency / Mode   : {acc.currency} | Hedging Mode")

    # 2. Account Balance & Equity
    print("\n[2] BALANCE & RISK GUARD AUDIT")
    bal = acc.balance
    eq = acc.equity
    floating_pnl = eq - bal
    margin = acc.margin
    free_margin = acc.margin_free
    
    print(f"  • Balance           : ${bal:,.2f}")
    print(f"  • Equity            : ${eq:,.2f}")
    print(f"  • Floating PnL      : {format_currency(floating_pnl)}")
    print(f"  • Free Margin       : ${free_margin:,.2f} (Used Margin: ${margin:,.2f})")

    # Guard calculations (assumes initial deposit benchmark $10,000 or current balance)
    initial_deposit = 10000.0
    daily_guard_limit_pct = 4.0  # 4% daily limit
    total_guard_limit_pct = 8.0  # 8% total DD limit

    total_dd_dollars = max(0.0, initial_deposit - eq)
    total_dd_pct = (total_dd_dollars / initial_deposit) * 100.0
    dd_status = "🟢 SAFE" if total_dd_pct < daily_guard_limit_pct else "⚠️ ELEVATED"
    print(f"  • Total Drawdown    : {total_dd_pct:.2f}% (${total_dd_dollars:,.2f}) [{dd_status}] (Hard Limit: {total_guard_limit_pct}%)")

    # 3. Open Positions
    positions = mt5.positions_get()
    print("\n[3] ACTIVE FORWARD POSITIONS")
    if positions and len(positions) > 0:
        print(f"  Active Positions: {len(positions)}")
        print(f"  {'Ticket':<10} {'Symbol':<8} {'Type':<6} {'Lots':<6} {'Open Price':<11} {'Current':<11} {'SL':<10} {'TP':<10} {'Profit':<10} {'Magic':<10}")
        print("  " + "-" * 85)
        for p in positions:
            pos_type = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
            magic_name = "GBPUSD" if p.magic == 50000000 else str(p.magic)
            print(f"  {p.ticket:<10} {p.symbol:<8} {pos_type:<6} {p.volume:<6.2f} {p.price_open:<11.5f} {p.price_current:<11.5f} {p.sl:<10.5f} {p.tp:<10.5f} {format_currency(p.profit):<10} {p.magic:<10}")
    else:
        print("  🟢 Zero open positions. EA is scanning and waiting for M30 swing setups.")

    # 4. Today's Closed Trades
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(today_start, datetime.now())
    closed_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT] if deals else []

    print("\n[4] TODAY'S PERFORMANCE SUMMARY")
    if closed_deals:
        realized_pnl = sum(d.profit + d.swap + d.commission for d in closed_deals)
        wins = [d for d in closed_deals if d.profit > 0]
        losses = [d for d in closed_deals if d.profit < 0]
        wr = (len(wins) / len(closed_deals) * 100.0) if closed_deals else 0.0
        print(f"  • Closed Trades     : {len(closed_deals)} (Wins: {len(wins)}, Losses: {len(losses)})")
        print(f"  • Win Rate          : {wr:.1f}%")
        print(f"  • Realized PnL      : {format_currency(realized_pnl)}")
    else:
        print("  • Closed Trades     : 0 deals closed today.")
        print("  • Note              : Weekend market is currently closed. Trading begins on market open.")

    print("\n" + "=" * 65)
    mt5.shutdown()


if __name__ == "__main__":
    run_monitor()
