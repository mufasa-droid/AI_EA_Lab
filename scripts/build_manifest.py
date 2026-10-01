"""
AI EA Lab - Experiment Manifest Builder

Scans the experiments/ archive, validates data integrity, resolves research
dataset classifications, and generates experiments/manifest.json deterministically.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.research_periods import load_research_periods
from scripts.validation import validate_experiment_dir

EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
MANIFEST_PATH = EXPERIMENTS_DIR / "manifest.json"


def natural_sort_key(exp_id: str):
    """
    Sort key to sort experiment IDs numerically (e.g. EXP-0001, EXP-0002).
    """
    match = re.search(r"\d+", exp_id)
    if match:
        return (0, int(match.group(0)), exp_id)
    return (1, 0, exp_id)


def extract_manifest_entry(
    exp_dir: Path,
    val_result: Dict[str, Any],
    project_root: Path,
) -> Dict[str, Any]:
    """
    Extracts a standardized, lightweight manifest entry from experiment files.
    Missing metrics are safely recorded as null.
    """
    metadata = val_result.get("metadata") or {}
    metrics_root = val_result.get("metrics") or {}
    settings = metrics_root.get("settings") or {}
    metrics = metrics_root.get("metrics") or {}

    exp_id = metadata.get("experiment_id") or exp_dir.name
    created_at = metadata.get("created_at")

    ea_name = metadata.get("ea") or settings.get("expert")
    symbol = metadata.get("symbol") or settings.get("symbol")
    timeframe = metadata.get("timeframe") or settings.get("timeframe")
    from_date = metadata.get("from") or settings.get("from")
    to_date = metadata.get("to") or settings.get("to")

    net_profit = metrics.get("total_net_profit")
    profit_factor = metrics.get("profit_factor")
    total_trades = metrics.get("total_trades")

    # Drawdown extraction (handle dict or primitive float)
    max_dd = None
    eq_dd = metrics.get("equity_drawdown_maximal")
    bal_dd = metrics.get("balance_drawdown_maximal")

    if isinstance(eq_dd, dict):
        max_dd = eq_dd.get("value")
    elif isinstance(eq_dd, (int, float)):
        max_dd = float(eq_dd)
    elif isinstance(bal_dd, dict):
        max_dd = bal_dd.get("value")
    elif isinstance(bal_dd, (int, float)):
        max_dd = float(bal_dd)

    # Relative path formatted with forward slashes
    try:
        rel_path = exp_dir.relative_to(project_root).as_posix()
    except ValueError:
        rel_path = f"experiments/{exp_dir.name}"

    return {
        "id": exp_id,
        "created_at": created_at,
        "ea": ea_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "from": from_date,
        "to": to_date,
        "net_profit": net_profit,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "max_drawdown": max_dd,
        "dataset": val_result.get("dataset"),
        "dataset_status": val_result.get("dataset_status"),
        "validation_passed": val_result.get("is_valid", False),
        "experiment_path": rel_path,
    }


def build_manifest(
    experiments_dir: Optional[Path] = None,
    output_path: Optional[Path] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """
    Scans experiments directory, builds deterministic manifest dictionary,
    and writes experiments/manifest.json.
    """
    exp_dir_path = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    out_path = Path(output_path) if output_path else (exp_dir_path / "manifest.json")

    if not exp_dir_path.exists():
        exp_dir_path.mkdir(parents=True, exist_ok=True)

    periods_config = load_research_periods()

    valid_entries: List[Dict[str, Any]] = []
    invalid_reports: List[Dict[str, Any]] = []
    seen_ids: Dict[str, str] = {}

    subdirs = [p for p in exp_dir_path.iterdir() if p.is_dir()]

    for entry in sorted(subdirs, key=lambda p: natural_sort_key(p.name)):
        val_result = validate_experiment_dir(entry, periods_config=periods_config)

        if not val_result["is_valid"]:
            # Report invalid / incomplete experiment gracefully
            report_info = {
                "directory": entry.name,
                "issues": val_result["issues"],
            }
            invalid_reports.append(report_info)
            if not quiet:
                print(
                    f"[WARNING] Invalid experiment directory '{entry.name}': "
                    f"{'; '.join(val_result['issues'])}",
                    file=sys.stderr,
                )
            continue

        manifest_entry = extract_manifest_entry(entry, val_result, PROJECT_ROOT)
        exp_id = manifest_entry["id"]

        # Check duplicate experiment IDs
        if exp_id in seen_ids:
            warning_msg = (
                f"Duplicate experiment ID '{exp_id}' found in '{entry.name}' "
                f"(already seen in '{seen_ids[exp_id]}'). Skipping duplicate."
            )
            invalid_reports.append({"directory": entry.name, "issues": [warning_msg]})
            if not quiet:
                print(f"[WARNING] {warning_msg}", file=sys.stderr)
            continue

        seen_ids[exp_id] = entry.name
        valid_entries.append(manifest_entry)

    # Deterministic sort by experiment ID
    valid_entries.sort(key=lambda item: natural_sort_key(item["id"]))

    manifest_data = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "total_experiments": len(valid_entries),
        "experiments": valid_entries,
    }

    if invalid_reports:
        manifest_data["invalid_experiments_count"] = len(invalid_reports)
        manifest_data["invalid_experiments"] = invalid_reports

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(manifest_data, indent=2),
        encoding="utf-8",
    )

    if not quiet:
        print("=" * 60)
        print("AI EA LAB - MANIFEST BUILDER")
        print("=" * 60)
        print(f"Scanned directory  : {exp_dir_path}")
        print(f"Valid experiments  : {len(valid_entries)}")
        for e in valid_entries:
            print(
                f"  - {e['id']}: EA={e['ea']}, Symbol={e['symbol']}, "
                f"Period={e['from']}->{e['to']}, NetProfit={e['net_profit']}, "
                f"Dataset={e['dataset'] or e['dataset_status']}"
            )
        if invalid_reports:
            print(f"Invalid directories: {len(invalid_reports)}")
            for inv in invalid_reports:
                print(f"  ! {inv['directory']}: {', '.join(inv['issues'])}")
        print(f"Manifest written to: {out_path}")
        print("=" * 60)

    return manifest_data


def main():
    parser = argparse.ArgumentParser(
        description="Build or deterministic rebuild of experiments/manifest.json."
    )
    parser.add_argument(
        "--experiments-dir",
        "-d",
        default=None,
        help="Path to experiments directory (default: experiments/)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Path to output manifest.json (default: experiments/manifest.json)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress console output",
    )
    args = parser.parse_args()

    build_manifest(
        experiments_dir=args.experiments_dir,
        output_path=args.output,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
