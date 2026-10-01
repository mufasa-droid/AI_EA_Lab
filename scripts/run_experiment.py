"""
AI EA Lab - End-to-End Automated Experiment Runner
Orchestrates: Backtest -> MT5 Report -> Parser -> Experiment Storage -> Archive -> Metrics/Metadata
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest import (
    load_config,
    create_tester_config,
    run_backtest,
    verify_report,
    check_port_conflict,
)
from scripts.parse_report import parse_report

EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"


def get_next_experiment_id(experiments_dir: Path) -> str:
    """
    Finds the next sequential experiment ID formatted as EXP-XXXX.
    Ensures existing experiments are never overwritten.
    """
    experiments_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = []

    for entry in experiments_dir.iterdir():
        if entry.is_dir():
            match = re.match(r"^EXP-(\d+)$", entry.name, re.IGNORECASE)
            if match:
                existing_ids.append(int(match.group(1)))

    next_num = max(existing_ids) + 1 if existing_ids else 1
    return f"EXP-{next_num:04d}"


def get_file_info(file_path: Path):
    """
    Returns file metadata and SHA256 checksum safely if the file exists.
    """
    if not file_path.exists():
        return None

    try:
        content = file_path.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()
        mtime = datetime.fromtimestamp(file_path.stat().st_mtime).astimezone().isoformat()
        return {
            "filename": file_path.name,
            "size_bytes": file_path.stat().st_size,
            "last_modified": mtime,
            "sha256": sha256,
        }
    except Exception:
        return None


def get_git_commit(project_root: Path):
    """
    Safely retrieves the current git commit hash if in a git repository.
    Returns None if not a git repository or git command fails.
    """
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def run_experiment(note: str = None):
    """
    Executes the full experiment pipeline:
    1. Pre-flight checks and configuration
    2. Runs MT5 Strategy Tester backtest
    3. Verifies report existence and execution
    4. Parses report into structured metrics
    5. Archives report, charts, metrics, and metadata under experiments/EXP-XXXX
    """
    print("=" * 60)
    print("AI EA LAB - STARTING EXPERIMENT PIPELINE")
    print("=" * 60)
    print()

    # 1. Pre-flight check for port 3000 (MT5 tester core)
    port_ok = check_port_conflict()
    if not port_ok:
        print("Note: Proceeding, but tester agent may encounter port binding conflict.")

    # 2. Load project configuration
    config = load_config()

    # 3. Create tester configuration (backtest.ini) and ensure EA is synced
    tester_config_path, report_path = create_tester_config(config)
    print(f"Tester config ready : {tester_config_path}")
    print(f"Expected report     : {report_path}")
    print()

    # 4. Run MT5 Strategy Tester
    return_code = run_backtest(config, tester_config_path)
    if return_code != 0:
        raise SystemExit(
            f"ERROR: MT5 Strategy Tester exited with non-zero code: {return_code}"
        )

    # 5. Verify report was generated, non-empty, and has valid execution metrics
    report_valid = verify_report(report_path)
    if not report_valid:
        raise SystemExit(
            "ERROR: Backtest completed but report verification failed."
        )

    # Project copy of report in tester/reports
    project_report_path = PROJECT_ROOT / "tester" / "reports" / report_path.name
    if not project_report_path.exists():
        raise FileNotFoundError(
            f"Expected project report not found at {project_report_path}"
        )

    print()
    print("=" * 60)
    print("PARSING REPORT METRICS")
    print("=" * 60)

    # 6. Parse report into structured metrics
    parsed_result = parse_report(project_report_path)
    if not parsed_result["validation"]["test_executed"]:
        print(
            "WARNING: Test report indicates test might not have fully executed "
            "(bars/ticks/history quality missing or zero)."
        )

    # 7. Create unique experiment storage
    exp_id = get_next_experiment_id(EXPERIMENTS_DIR)
    exp_dir = EXPERIMENTS_DIR / exp_id
    charts_dir = exp_dir / "charts"

    exp_dir.mkdir(parents=True, exist_ok=False)
    charts_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 60)
    print(f"ARCHIVING EXPERIMENT: {exp_id}")
    print("=" * 60)
    print(f"Destination: {exp_dir}")

    # 8. Copy HTML report into experiment directory
    exp_report_path = exp_dir / "report.htm"
    shutil.copy2(project_report_path, exp_report_path)
    print(f"Copied report : {exp_report_path.name}")

    # 9. Copy chart assets into charts/ subfolder
    chart_files = []
    source_reports_dir = project_report_path.parent
    stem = project_report_path.stem

    for asset in source_reports_dir.glob(f"{stem}*.png"):
        dest_chart = charts_dir / asset.name
        shutil.copy2(asset, dest_chart)
        chart_files.append(f"charts/{asset.name}")
        print(f"Copied chart  : {asset.name}")

    # 10. Save metrics.json
    metrics_path = exp_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(parsed_result, indent=2),
        encoding="utf-8",
    )
    print(f"Saved metrics : {metrics_path.name}")

    # 11. Compile and save metadata.json
    ea_name = config["ea"]["name"]
    ea_mq5_path = PROJECT_ROOT / "ea" / f"{ea_name}.mq5"
    ea_ex5_path = PROJECT_ROOT / "ea" / f"{ea_name}.ex5"

    metadata = {
        "experiment_id": exp_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "note": note,
        "ea": ea_name,
        "symbol": config["backtest"]["symbol"],
        "timeframe": config["backtest"]["timeframe"],
        "from": config["backtest"]["from"],
        "to": config["backtest"]["to"],
        "report": "report.htm",
        "metrics": "metrics.json",
        "charts": chart_files,
        "ea_source": get_file_info(ea_mq5_path),
        "ea_binary": get_file_info(ea_ex5_path),
        "backtest_config": config["backtest"],
        "inputs": parsed_result["settings"]["inputs"],
        "git_commit": get_git_commit(PROJECT_ROOT),
        "parser_schema_version": parsed_result.get("schema_version", 1),
        "status": "COMPLETED",
    }

    metadata_path = exp_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    print(f"Saved metadata: {metadata_path.name}")

    # 12. Print clear experiment summary
    settings = parsed_result["settings"]
    metrics = parsed_result["metrics"]
    drawdown = metrics.get("equity_drawdown_maximal") or metrics.get("balance_drawdown_maximal") or {}

    inputs_str = ", ".join(f"{k}={v}" for k, v in settings["inputs"].items()) if settings["inputs"] else "None"

    print()
    print("=" * 60)
    print("AI EA LAB - EXPERIMENT SUMMARY")
    print("=" * 60)
    print(f"Experiment ID   : {exp_id}")
    print(f"Directory       : {exp_dir.resolve()}")
    print(f"EA              : {settings['expert']}")
    print(f"Symbol          : {settings['symbol']}")
    print(f"Timeframe       : {settings['timeframe']}")
    print(f"Period          : {settings['from']} -> {settings['to']}")
    print(f"History Quality : {metrics['history_quality_percent']}%")
    print(f"Bars / Ticks    : {metrics['bars']:,} / {metrics['ticks']:,}")
    print(f"Total Trades    : {metrics['total_trades']} (Deals: {metrics['total_deals']})")
    print(f"Total Net Profit: {metrics['total_net_profit']:.2f} {settings.get('currency') or ''}")
    print(f"Profit Factor   : {metrics['profit_factor']:.2f}")
    if isinstance(drawdown, dict):
        dd_val = drawdown.get("value")
        dd_pct = drawdown.get("percent")
        print(f"Max Drawdown    : {dd_val} ({dd_pct}%)")
    print(f"Inputs          : {inputs_str}")
    print(f"Execution State : {'VERIFIED' if parsed_result['validation']['test_executed'] else 'UNVERIFIED'}")
    print(f"Status          : SUCCESS")
    print("=" * 60)
    print()

    # 13. Update manifest index
    try:
        from scripts.build_manifest import build_manifest
        manifest = build_manifest(quiet=True)
        print(f"Experiment Manifest Updated: {manifest.get('total_experiments', 0)} experiments indexed.")
        print()
    except Exception as e:
        print(f"Note: Manifest update encountered an error: {e}")

    return exp_id, exp_dir


def main():
    parser = argparse.ArgumentParser(
        description="Run an automated MT5 backtest experiment and archive results."
    )
    parser.add_argument(
        "--note",
        "-n",
        default=None,
        help="Optional note describing this experiment run",
    )
    args = parser.parse_args()

    run_experiment(note=args.note)


if __name__ == "__main__":
    main()
