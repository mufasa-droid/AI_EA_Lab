"""
Experiment Validation Module

Provides lightweight factual research-quality and data integrity checks.
Focuses strictly on reproducibility, data integrity, and file completeness.
Does NOT compute profitability scores or make subjective strategy evaluations.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.research_periods import classify_experiment_period, load_research_periods


def validate_experiment_dir(
    exp_dir: Path,
    periods_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Validates the data integrity of an experiment directory.
    Checks:
    - Experiment directory naming format (e.g. EXP-0001)
    - Metadata existence and valid JSON structure
    - Metrics existence and valid JSON structure
    - HTML Report existence and non-zero size
    - History quality percent present
    - Bars > 0
    - Ticks > 0
    - Test execution validity flag
    - Research period classification resolved (classified, unconfigured, ambiguous, or out_of_bounds)
    """
    exp_dir = Path(exp_dir)
    issues: List[str] = []
    checks: Dict[str, bool] = {
        "dir_exists": exp_dir.is_dir(),
        "id_valid_format": bool(re.match(r"^EXP-\d{4,}$", exp_dir.name, re.IGNORECASE)),
        "metadata_exists": False,
        "metrics_exists": False,
        "report_exists": False,
        "report_non_empty": False,
        "history_quality_present": False,
        "bars_positive": False,
        "ticks_positive": False,
        "test_executed": False,
        "period_status_known": False,
    }

    if not checks["dir_exists"]:
        issues.append(f"Experiment directory does not exist: {exp_dir}")
        return {
            "is_valid": False,
            "checks": checks,
            "issues": issues,
            "metadata": None,
            "metrics": None,
            "dataset": None,
            "dataset_status": "unresolved",
        }

    if not checks["id_valid_format"]:
        issues.append(f"Directory name '{exp_dir.name}' does not match expected pattern EXP-XXXX")

    metadata = None
    metadata_file = exp_dir / "metadata.json"
    if metadata_file.is_file():
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            if isinstance(metadata, dict):
                checks["metadata_exists"] = True
            else:
                issues.append("metadata.json is not a valid JSON object")
        except Exception as e:
            issues.append(f"Failed to read/parse metadata.json: {e}")
    else:
        issues.append("metadata.json missing")

    metrics = None
    metrics_file = exp_dir / "metrics.json"
    if metrics_file.is_file():
        try:
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
            if isinstance(metrics, dict):
                checks["metrics_exists"] = True
            else:
                issues.append("metrics.json is not a valid JSON object")
        except Exception as e:
            issues.append(f"Failed to read/parse metrics.json: {e}")
    else:
        issues.append("metrics.json missing")

    report_file = exp_dir / "report.htm"
    if report_file.is_file():
        checks["report_exists"] = True
        if report_file.stat().st_size > 0:
            checks["report_non_empty"] = True
        else:
            issues.append("report.htm is empty (0 bytes)")
    else:
        issues.append("report.htm missing")

    # Inspect metrics details if available
    if metrics and isinstance(metrics.get("metrics"), dict):
        m = metrics["metrics"]
        hq = m.get("history_quality_percent")
        if hq is not None:
            checks["history_quality_present"] = True
        else:
            issues.append("History Quality metric missing in metrics.json")

        bars = m.get("bars")
        if bars is not None and isinstance(bars, (int, float)) and bars > 0:
            checks["bars_positive"] = True
        else:
            issues.append(f"Bars count is not > 0: {bars}")

        ticks = m.get("ticks")
        if ticks is not None and isinstance(ticks, (int, float)) and ticks > 0:
            checks["ticks_positive"] = True
        else:
            issues.append(f"Ticks count is not > 0: {ticks}")

    # Inspect test executed flag
    if metrics and isinstance(metrics.get("validation"), dict):
        test_exec = metrics["validation"].get("test_executed")
        if test_exec is True:
            checks["test_executed"] = True
        else:
            issues.append("metrics.validation.test_executed is not True")
    elif checks["bars_positive"] and checks["ticks_positive"] and checks["history_quality_present"]:
        checks["test_executed"] = True

    # Check period classification
    if periods_config is None:
        periods_config = load_research_periods()

    from_date = None
    to_date = None
    if metadata:
        from_date = metadata.get("from")
        to_date = metadata.get("to")
    if not from_date and metrics and isinstance(metrics.get("settings"), dict):
        from_date = metrics["settings"].get("from")
        to_date = metrics["settings"].get("to")

    dataset, dataset_status = classify_experiment_period(from_date, to_date, periods_config)
    checks["period_status_known"] = dataset_status in {
        "classified",
        "unconfigured",
        "ambiguous",
        "out_of_bounds",
    }

    # An experiment is considered valid if the core files and execution metrics are sound
    is_valid = (
        checks["metadata_exists"]
        and checks["metrics_exists"]
        and checks["report_exists"]
        and checks["report_non_empty"]
        and checks["history_quality_present"]
        and checks["bars_positive"]
        and checks["ticks_positive"]
        and checks["test_executed"]
    )

    return {
        "is_valid": is_valid,
        "checks": checks,
        "issues": issues,
        "metadata": metadata,
        "metrics": metrics,
        "dataset": dataset,
        "dataset_status": dataset_status,
    }
