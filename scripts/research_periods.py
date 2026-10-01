"""
Research Periods Configuration & Classification Module

Manages research dataset splits (TRAINING, VALIDATION, UNSEEN).
Provides deterministic classification of experiment date ranges without guessing.
"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "research_periods.json"


def parse_date(date_str: Optional[str]):
    """
    Parses date formatted as 'YYYY.MM.DD' or 'YYYY-MM-DD' into a date object.
    Returns None if date_str is invalid, empty, or None.
    """
    if not date_str:
        return None
    cleaned = str(date_str).strip()
    # Normalize separators
    cleaned = cleaned.replace("/", ".").replace("-", ".")
    match = re.match(r"^(\d{4})\.(\d{2})\.(\d{2})$", cleaned)
    if match:
        try:
            return datetime.strptime(cleaned, "%Y.%m.%d").date()
        except ValueError:
            return None
    return None


def load_research_periods(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Loads the research periods configuration.
    Returns default unconfigured structure if file does not exist or is invalid.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        return {
            "schema_version": 1,
            "status": "unconfigured",
            "note": "Research period dates are unconfigured placeholders.",
            "periods": {
                "training": {"from": None, "to": None},
                "validation": {"from": None, "to": None},
                "unseen": {"from": None, "to": None},
            },
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Root configuration must be a JSON object.")
        return data
    except Exception as e:
        return {
            "schema_version": 1,
            "status": "error",
            "error": str(e),
            "periods": {
                "training": {"from": None, "to": None},
                "validation": {"from": None, "to": None},
                "unseen": {"from": None, "to": None},
            },
        }


def is_periods_configured(periods_config: Dict[str, Any]) -> bool:
    """
    Returns True if at least one period has valid, non-null from and to dates.
    """
    periods = periods_config.get("periods", {})
    if not isinstance(periods, dict):
        return False

    for name, p_data in periods.items():
        if isinstance(p_data, dict):
            p_from = parse_date(p_data.get("from"))
            p_to = parse_date(p_data.get("to"))
            if p_from is not None and p_to is not None:
                return True
    return False


def resolve_dataset_partition(
    partition_name: Optional[str],
    config_path: Optional[Path] = None,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str], str]:
    """
    Resolves a requested dataset partition name against research_periods.json.
    Returns (success, normalized_partition_name, from_date, to_date, status_code).
    """
    if not partition_name or not isinstance(partition_name, str) or not partition_name.strip():
        return False, None, None, None, "DATASET_MISSING"

    norm_name = partition_name.strip().lower()
    valid_partitions = {"training", "validation", "unseen"}
    if norm_name not in valid_partitions:
        return False, norm_name, None, None, "INVALID_DATASET"

    periods_cfg = load_research_periods(config_path)
    if not is_periods_configured(periods_cfg):
        return False, norm_name, None, None, "UNCONFIGURED"

    periods = periods_cfg.get("periods", {})
    target = periods.get(norm_name, {})
    p_from = target.get("from")
    p_to = target.get("to")

    if not p_from or not p_to:
        return False, norm_name, None, None, "UNCONFIGURED"

    return True, norm_name, p_from, p_to, "RESOLVED"


def classify_experiment_period(
    from_date_str: Optional[str],
    to_date_str: Optional[str],
    periods_config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], str]:
    """
    Classifies an experiment date range into one of the research periods.

    Returns:
        (dataset_label, status_string)

    Possible statuses:
        - "classified": Experiment is fully contained within exactly one period.
                        dataset_label will be "training", "validation", or "unseen".
        - "ambiguous": Experiment overlaps multiple periods or partially spills across boundaries.
        - "out_of_bounds": Experiment falls entirely outside all configured periods.
        - "unconfigured": Research periods are not yet configured with concrete dates.
        - "unspecified": Experiment has no from/to date.
        - "invalid_date_range": from_date is after to_date or date format cannot be parsed.
    """
    if not from_date_str or not to_date_str:
        return None, "unspecified"

    exp_from = parse_date(from_date_str)
    exp_to = parse_date(to_date_str)

    if exp_from is None or exp_to is None:
        return None, "invalid_date_format"

    if exp_from > exp_to:
        return None, "invalid_date_range"

    if periods_config is None:
        periods_config = load_research_periods()

    if not is_periods_configured(periods_config):
        return None, "unconfigured"

    periods = periods_config.get("periods", {})
    containing_periods = []
    overlapping_periods = []

    for name, p_data in periods.items():
        if not isinstance(p_data, dict):
            continue
        p_from = parse_date(p_data.get("from"))
        p_to = parse_date(p_data.get("to"))
        if p_from is None or p_to is None or p_from > p_to:
            continue

        # Check overlap: max(start1, start2) <= min(end1, end2)
        overlaps = max(exp_from, p_from) <= min(exp_to, p_to)
        # Check containment: start2 <= start1 and end1 <= end2
        is_contained = p_from <= exp_from and exp_to <= p_to

        if overlaps:
            overlapping_periods.append(name)
        if is_contained:
            containing_periods.append(name)

    # Classification rules:
    # 1. Exactly one period contains the experiment and no other period is touched
    if len(containing_periods) == 1 and len(overlapping_periods) == 1:
        return containing_periods[0], "classified"

    # 2. Overlaps multiple periods
    if len(overlapping_periods) > 1:
        return None, "ambiguous"

    # 3. Partially overlaps one period but is not fully contained in it
    if len(overlapping_periods) == 1 and len(containing_periods) == 0:
        return None, "ambiguous"

    # 4. Overlaps no period at all
    return None, "out_of_bounds"


def validate_research_periods_integrity(
    periods_config: Optional[Dict[str, Any]] = None
) -> Tuple[bool, List[str]]:
    """
    Validates the dataset partition integrity of research periods:
    1. training, validation, unseen periods exist
    2. Dates are valid (from <= to for each period)
    3. Chronological sequence (training.to < validation.from < validation.to < unseen.from)
    4. No overlaps between periods
    5. Boundary correctness (day-adjacent boundaries between consecutive periods)
    """
    if periods_config is None:
        periods_config = load_research_periods()

    issues: List[str] = []
    periods = periods_config.get("periods", {})
    if not isinstance(periods, dict):
        return False, ["Periods configuration must be a dictionary."]

    required_keys = ["training", "validation", "unseen"]
    parsed_periods: Dict[str, Tuple[datetime.date, datetime.date]] = {}

    for key in required_keys:
        if key not in periods or not isinstance(periods[key], dict):
            issues.append(f"Required period '{key}' is missing or invalid.")
            continue
        p_from = parse_date(periods[key].get("from"))
        p_to = parse_date(periods[key].get("to"))
        if p_from is None or p_to is None:
            issues.append(f"Period '{key}' has invalid or missing date boundaries.")
            continue
        if p_from > p_to:
            issues.append(f"Period '{key}' has start date after end date ({p_from} > {p_to}).")
            continue
        parsed_periods[key] = (p_from, p_to)

    if issues:
        return False, issues

    train_from, train_to = parsed_periods["training"]
    val_from, val_to = parsed_periods["validation"]
    unseen_from, unseen_to = parsed_periods["unseen"]

    # 1. Chronological order
    if not (train_to < val_from and val_to < unseen_from):
        issues.append("Periods are not in strict chronological order.")

    # 2. Overlap check
    pairs = [
        ("training", train_from, train_to),
        ("validation", val_from, val_to),
        ("unseen", unseen_from, unseen_to),
    ]
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            name1, start1, end1 = pairs[i]
            name2, start2, end2 = pairs[j]
            if max(start1, start2) <= min(end1, end2):
                issues.append(f"Period '{name1}' overlaps with period '{name2}'.")

    # 3. Boundary continuity (adjacent days)
    if train_to + timedelta(days=1) != val_from:
        issues.append(f"Boundary gap or misalignment between training ({train_to}) and validation ({val_from}).")

    if val_to + timedelta(days=1) != unseen_from:
        issues.append(f"Boundary gap or misalignment between validation ({val_to}) and unseen ({unseen_from}).")

    return len(issues) == 0, issues
