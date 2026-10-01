"""
AI EA Lab - Experiment Comparison Tool

Compares two or more experiments side-by-side across settings, data quality,
performance, risk, and trading metrics.
Outputs factual differences without ranking, scoring, or labeling "winners".
Supports human-readable CLI formatting and machine-readable JSON output (--json).
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"


def find_available_experiments(experiments_dir: Path) -> List[str]:
    """
    Returns sorted list of available experiment directory names.
    """
    if not experiments_dir.exists():
        return []
    return sorted([
        d.name for d in experiments_dir.iterdir()
        if d.is_dir() and (d / "metrics.json").exists()
    ])


def load_experiment(exp_id: str, experiments_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Loads experiment metadata.json and metrics.json for a given experiment ID.
    Raises FileNotFoundError if experiment directory or required files are missing.
    """
    base_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    exp_dir = base_dir / exp_id

    if not exp_dir.exists() or not exp_dir.is_dir():
        raise FileNotFoundError(f"Experiment directory not found: {exp_id}")

    metrics_file = exp_dir / "metrics.json"
    if not metrics_file.exists():
        raise FileNotFoundError(f"metrics.json missing in experiment: {exp_id}")

    try:
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Failed to parse metrics.json in {exp_id}: {e}")

    metadata = {}
    metadata_file = exp_dir / "metadata.json"
    if metadata_file.exists():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    return {
        "id": exp_id,
        "dir": exp_dir,
        "metadata": metadata,
        "metrics": metrics,
    }


def safe_diff(val_a: Any, val_b: Any) -> Optional[float]:
    """
    Computes numerical difference (val_b - val_a) safely.
    Returns None if either value is not a number.
    """
    if val_a is None or val_b is None:
        return None
    try:
        f_a = float(val_a)
        f_b = float(val_b)
        return round(f_b - f_a, 6)
    except (ValueError, TypeError):
        return None


def extract_comparison_data(exp_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extracts structured comparison fields from experiment data dictionary.
    """
    metadata = exp_data.get("metadata") or {}
    metrics_root = exp_data.get("metrics") or {}
    settings = metrics_root.get("settings") or {}
    m = metrics_root.get("metrics") or {}

    def extract_val_pct(obj):
        if isinstance(obj, dict):
            return obj.get("value"), obj.get("percent")
        if isinstance(obj, (int, float)):
            return float(obj), None
        return None, None

    def extract_count_pct(obj):
        if isinstance(obj, dict):
            return obj.get("count"), obj.get("percent")
        if isinstance(obj, int):
            return obj, None
        return None, None

    bal_dd_max_val, bal_dd_max_pct = extract_val_pct(m.get("balance_drawdown_maximal"))
    eq_dd_max_val, eq_dd_max_pct = extract_val_pct(m.get("equity_drawdown_maximal"))
    bal_dd_rel_val, bal_dd_rel_pct = extract_val_pct(m.get("balance_drawdown_relative"))
    eq_dd_rel_val, eq_dd_rel_pct = extract_val_pct(m.get("equity_drawdown_relative"))

    profit_trades_count, profit_trades_pct = extract_count_pct(m.get("profit_trades"))
    loss_trades_count, loss_trades_pct = extract_count_pct(m.get("loss_trades"))
    long_trades_count, long_trades_pct = extract_count_pct(m.get("long_trades"))
    short_trades_count, short_trades_pct = extract_count_pct(m.get("short_trades"))

    inputs = metadata.get("inputs") or settings.get("inputs") or {}
    inputs_str = ", ".join(f"{k}={v}" for k, v in sorted(inputs.items())) if inputs else "None"

    return {
        "settings": {
            "ea": metadata.get("ea") or settings.get("expert"),
            "symbol": metadata.get("symbol") or settings.get("symbol"),
            "timeframe": metadata.get("timeframe") or settings.get("timeframe"),
            "from": metadata.get("from") or settings.get("from"),
            "to": metadata.get("to") or settings.get("to"),
            "initial_deposit": settings.get("initial_deposit"),
            "leverage": settings.get("leverage"),
            "inputs": inputs,
            "inputs_display": inputs_str,
        },
        "data_quality": {
            "history_quality_percent": m.get("history_quality_percent"),
            "bars": m.get("bars"),
            "ticks": m.get("ticks"),
        },
        "performance": {
            "total_net_profit": m.get("total_net_profit"),
            "gross_profit": m.get("gross_profit"),
            "gross_loss": m.get("gross_loss"),
            "profit_factor": m.get("profit_factor"),
            "expected_payoff": m.get("expected_payoff"),
            "recovery_factor": m.get("recovery_factor"),
            "sharpe_ratio": m.get("sharpe_ratio"),
        },
        "risk": {
            "balance_drawdown_absolute": m.get("balance_drawdown_absolute"),
            "equity_drawdown_absolute": m.get("equity_drawdown_absolute"),
            "balance_drawdown_maximal_value": bal_dd_max_val,
            "balance_drawdown_maximal_percent": bal_dd_max_pct,
            "equity_drawdown_maximal_value": eq_dd_max_val,
            "equity_drawdown_maximal_percent": eq_dd_max_pct,
            "balance_drawdown_relative_value": bal_dd_rel_val,
            "balance_drawdown_relative_percent": bal_dd_rel_pct,
            "equity_drawdown_relative_value": eq_dd_rel_val,
            "equity_drawdown_relative_percent": eq_dd_rel_pct,
        },
        "trading": {
            "total_trades": m.get("total_trades"),
            "total_deals": m.get("total_deals"),
            "profit_trades_count": profit_trades_count,
            "profit_trades_percent": profit_trades_pct,
            "loss_trades_count": loss_trades_count,
            "loss_trades_percent": loss_trades_pct,
            "long_trades_count": long_trades_count,
            "long_trades_percent": long_trades_pct,
            "short_trades_count": short_trades_count,
            "short_trades_percent": short_trades_pct,
            "average_profit_trade": m.get("average_profit_trade"),
            "average_loss_trade": m.get("average_loss_trade"),
        },
    }


def build_comparison_payload(
    exp_ids: List[str],
    experiments_data: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Constructs the structured JSON comparison dictionary.
    Computes pairwise changes between the first two experiments,
    and includes all experiment values for N experiments.
    """
    first_id = exp_ids[0]
    second_id = exp_ids[1] if len(exp_ids) > 1 else None

    flat_comparisons: Dict[str, Any] = {}
    categories_comparisons: Dict[str, Any] = {}

    first_data = experiments_data[first_id]

    for category, fields in first_data.items():
        categories_comparisons[category] = {}
        for field_name in fields.keys():
            metric_entry: Dict[str, Any] = {}
            for eid in exp_ids:
                metric_entry[eid] = experiments_data[eid][category].get(field_name)

            # If two experiments are compared, compute factual difference / equality
            if second_id:
                val1 = metric_entry[first_id]
                val2 = metric_entry[second_id]
                if isinstance(val1, (int, float)) and isinstance(val2, (int, float)):
                    metric_entry["change"] = safe_diff(val1, val2)
                elif val1 == val2:
                    metric_entry["identical"] = True
                else:
                    metric_entry["identical"] = False

            categories_comparisons[category][field_name] = metric_entry
            flat_comparisons[field_name] = metric_entry

    return {
        "schema_version": 1,
        "experiments": exp_ids,
        "comparisons": flat_comparisons,
        "categories": categories_comparisons,
    }


def format_num(val: Any, decimals: int = 2) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, int):
        return f"{val:,}"
    if isinstance(val, float):
        return f"{val:,.{decimals}f}"
    return str(val)


def format_change(diff: Optional[float], decimals: int = 2, is_pct: bool = False) -> str:
    if diff is None:
        return "N/A"
    sign = "+" if diff > 0 else ""
    unit = "%" if is_pct else ""
    return f"{sign}{diff:,.{decimals}f}{unit}"


def print_human_comparison(
    exp_ids: List[str],
    experiments_data: Dict[str, Dict[str, Any]],
    stream=sys.stdout,
):
    """
    Prints human-readable factual comparison report without ranking.
    """
    def out(text=""):
        print(text, file=stream)

    out("=" * 70)
    out("AI EA LAB - EXPERIMENT COMPARISON")
    out("=" * 70)
    out(f"Comparing: {' vs '.join(exp_ids)}")
    out()

    id_a = exp_ids[0]
    id_b = exp_ids[1] if len(exp_ids) > 1 else None
    data_a = experiments_data[id_a]
    data_b = experiments_data[id_b] if id_b else None

    # Helper for 2-experiment pair display
    def print_text_row(label: str, val_a: Any, val_b: Any):
        if id_b:
            status = "Unchanged" if val_a == val_b else "Changed"
            out(f"{label:<20}: {str(val_a)} -> {str(val_b)} ({status})")
        else:
            out(f"{label:<20}: {str(val_a)}")

    def print_metric_row(label: str, val_a: Any, val_b: Any, decimals: int = 2, is_pct: bool = False):
        if id_b:
            unit = "%" if is_pct else ""
            diff = safe_diff(val_a, val_b)
            chg_str = format_change(diff, decimals, is_pct)
            out(f"{label:<20}: {format_num(val_a, decimals)}{unit} -> {format_num(val_b, decimals)}{unit} (Change: {chg_str})")
        else:
            unit = "%" if is_pct else ""
            out(f"{label:<20}: {format_num(val_a, decimals)}{unit}")

    def print_compound_row(label: str, val_a: Any, pct_a: Any, val_b: Any, pct_b: Any, decimals: int = 2):
        if id_b:
            diff_val = safe_diff(val_a, val_b)
            diff_pct = safe_diff(pct_a, pct_b)
            left = f"{format_num(val_a, decimals)} ({format_num(pct_a, 2)}%)" if pct_a is not None else format_num(val_a, decimals)
            right = f"{format_num(val_b, decimals)} ({format_num(pct_b, 2)}%)" if pct_b is not None else format_num(val_b, decimals)
            chg = f"{format_change(diff_val, decimals)} / {format_change(diff_pct, 2, True)}"
            out(f"{label:<20}: {left} -> {right} (Change: {chg})")
        else:
            item = f"{format_num(val_a, decimals)} ({format_num(pct_a, 2)}%)" if pct_a is not None else format_num(val_a, decimals)
            out(f"{label:<20}: {item}")

    # 1. SETTINGS
    out("--- SETTINGS ---")
    s_a = data_a["settings"]
    s_b = data_b["settings"] if data_b else {}
    print_text_row("EA", s_a.get("ea"), s_b.get("ea"))
    print_text_row("Symbol", s_a.get("symbol"), s_b.get("symbol"))
    print_text_row("Timeframe", s_a.get("timeframe"), s_b.get("timeframe"))
    print_text_row("Period", f"{s_a.get('from')} - {s_a.get('to')}", f"{s_b.get('from')} - {s_b.get('to')}")
    print_metric_row("Initial Deposit", s_a.get("initial_deposit"), s_b.get("initial_deposit"), decimals=2)
    print_text_row("Leverage", s_a.get("leverage"), s_b.get("leverage"))
    print_text_row("Inputs", s_a.get("inputs_display"), s_b.get("inputs_display"))
    out()

    # 2. DATA QUALITY
    out("--- DATA QUALITY ---")
    dq_a = data_a["data_quality"]
    dq_b = data_b["data_quality"] if data_b else {}
    print_metric_row("History Quality", dq_a.get("history_quality_percent"), dq_b.get("history_quality_percent"), decimals=2, is_pct=True)
    print_metric_row("Bars", dq_a.get("bars"), dq_b.get("bars"), decimals=0)
    print_metric_row("Ticks", dq_a.get("ticks"), dq_b.get("ticks"), decimals=0)
    out()

    # 3. PERFORMANCE
    out("--- PERFORMANCE ---")
    p_a = data_a["performance"]
    p_b = data_b["performance"] if data_b else {}
    print_metric_row("Total Net Profit", p_a.get("total_net_profit"), p_b.get("total_net_profit"), decimals=2)
    print_metric_row("Gross Profit", p_a.get("gross_profit"), p_b.get("gross_profit"), decimals=2)
    print_metric_row("Gross Loss", p_a.get("gross_loss"), p_b.get("gross_loss"), decimals=2)
    print_metric_row("Profit Factor", p_a.get("profit_factor"), p_b.get("profit_factor"), decimals=2)
    print_metric_row("Expected Payoff", p_a.get("expected_payoff"), p_b.get("expected_payoff"), decimals=2)
    print_metric_row("Recovery Factor", p_a.get("recovery_factor"), p_b.get("recovery_factor"), decimals=2)
    print_metric_row("Sharpe Ratio", p_a.get("sharpe_ratio"), p_b.get("sharpe_ratio"), decimals=2)
    out()

    # 4. RISK
    out("--- RISK ---")
    r_a = data_a["risk"]
    r_b = data_b["risk"] if data_b else {}
    print_metric_row("Balance DD Abs", r_a.get("balance_drawdown_absolute"), r_b.get("balance_drawdown_absolute"), decimals=2)
    print_metric_row("Equity DD Abs", r_a.get("equity_drawdown_absolute"), r_b.get("equity_drawdown_absolute"), decimals=2)
    print_compound_row("Balance DD Max", r_a.get("balance_drawdown_maximal_value"), r_a.get("balance_drawdown_maximal_percent"),
                       r_b.get("balance_drawdown_maximal_value"), r_b.get("balance_drawdown_maximal_percent"), decimals=2)
    print_compound_row("Equity DD Max", r_a.get("equity_drawdown_maximal_value"), r_a.get("equity_drawdown_maximal_percent"),
                       r_b.get("equity_drawdown_maximal_value"), r_b.get("equity_drawdown_maximal_percent"), decimals=2)
    print_compound_row("Balance DD Rel", r_a.get("balance_drawdown_relative_value"), r_a.get("balance_drawdown_relative_percent"),
                       r_b.get("balance_drawdown_relative_value"), r_b.get("balance_drawdown_relative_percent"), decimals=2)
    print_compound_row("Equity DD Rel", r_a.get("equity_drawdown_relative_value"), r_a.get("equity_drawdown_relative_percent"),
                       r_b.get("equity_drawdown_relative_value"), r_b.get("equity_drawdown_relative_percent"), decimals=2)
    out()

    # 5. TRADING
    out("--- TRADING ---")
    t_a = data_a["trading"]
    t_b = data_b["trading"] if data_b else {}
    print_metric_row("Total Trades", t_a.get("total_trades"), t_b.get("total_trades"), decimals=0)
    print_metric_row("Total Deals", t_a.get("total_deals"), t_b.get("total_deals"), decimals=0)
    print_compound_row("Profit Trades", t_a.get("profit_trades_count"), t_a.get("profit_trades_percent"),
                       t_b.get("profit_trades_count"), t_b.get("profit_trades_percent"), decimals=0)
    print_compound_row("Loss Trades", t_a.get("loss_trades_count"), t_a.get("loss_trades_percent"),
                       t_b.get("loss_trades_count"), t_b.get("loss_trades_percent"), decimals=0)
    print_compound_row("Long Trades", t_a.get("long_trades_count"), t_a.get("long_trades_percent"),
                       t_b.get("long_trades_count"), t_b.get("long_trades_percent"), decimals=0)
    print_compound_row("Short Trades", t_a.get("short_trades_count"), t_a.get("short_trades_percent"),
                       t_b.get("short_trades_count"), t_b.get("short_trades_percent"), decimals=0)
    print_metric_row("Avg Profit Trade", t_a.get("average_profit_trade"), t_b.get("average_profit_trade"), decimals=2)
    print_metric_row("Avg Loss Trade", t_a.get("average_loss_trade"), t_b.get("average_loss_trade"), decimals=2)

    out("=" * 70)


def compare_experiments(
    exp_ids: List[str],
    experiments_dir: Optional[Path] = None,
    as_json: bool = False,
    output_stream=sys.stdout,
    err_stream=sys.stderr,
) -> int:
    """
    Entrypoint function to compare experiments.
    Returns 0 on success, 1 on error.
    """
    base_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR

    # Validate argument count
    if len(exp_ids) < 2:
        err_msg = f"At least two experiment IDs are required for comparison (received: {len(exp_ids)})"
        if as_json:
            print(json.dumps({"error": err_msg}), file=output_stream)
        else:
            print(f"Error: {err_msg}", file=err_stream)
            print("Usage: python scripts/compare_experiments.py EXP-0001 EXP-0002 [--json]", file=err_stream)
        return 1

    # Load each experiment
    experiments_data: Dict[str, Dict[str, Any]] = {}
    for eid in exp_ids:
        try:
            exp_raw = load_experiment(eid, experiments_dir=base_dir)
            experiments_data[eid] = extract_comparison_data(exp_raw)
        except FileNotFoundError:
            available = find_available_experiments(base_dir)
            available_str = ", ".join(available) if available else "None"
            if as_json:
                print(json.dumps({
                    "error": f"Experiment not found: {eid}",
                    "missing_experiment": eid,
                    "available_experiments": available,
                }, indent=2), file=output_stream)
            else:
                print(f"Experiment not found: {eid}", file=err_stream)
                print(f"Available experiments: {available_str}", file=err_stream)
            return 1
        except Exception as e:
            if as_json:
                print(json.dumps({"error": str(e), "experiment": eid}, indent=2), file=output_stream)
            else:
                print(f"Error loading {eid}: {e}", file=err_stream)
            return 1

    payload = build_comparison_payload(exp_ids, experiments_data)

    if as_json:
        print(json.dumps(payload, indent=2), file=output_stream)
    else:
        print_human_comparison(exp_ids, experiments_data, stream=output_stream)

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Compare two or more MT5 backtest experiments side-by-side."
    )
    parser.add_argument(
        "experiments",
        nargs="+",
        help="Experiment IDs to compare (e.g. EXP-0001 EXP-0002)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output comparison as structured JSON",
    )
    parser.add_argument(
        "--experiments-dir",
        "-d",
        default=None,
        help="Custom path to experiments directory (default: experiments/)",
    )
    args = parser.parse_args()

    exit_code = compare_experiments(
        exp_ids=args.experiments,
        experiments_dir=args.experiments_dir,
        as_json=args.as_json,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
