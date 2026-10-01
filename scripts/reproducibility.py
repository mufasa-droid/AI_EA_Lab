"""
AI EA Lab - Reproducibility & Robustness Layer (Phase 15)

Provides formal reproducibility contracts, deterministic configuration & identity fingerprinting,
non-sensitive environment metadata capture, repeat-execution verification, report isolation checks,
reproducibility comparison, candidate/experiment immutability auditing, and research-period tracking.

Enforces:
1. "Reproducibility" does NOT mean byte-for-byte raw report identity across separate MT5 runs.
2. Identity, Execution, Artifact, Parser, Provenance, Environment, and Dataset Reproducibility.
3. Deterministic SHA-256 fingerprinting excluding volatile timestamps, temporary paths, and secrets.
4. Repeat-run execution isolation (EXP-XXXX -> repeat EXP-YYYY referencing repeat_of_experiment_id).
5. NO strategy rankings, NO "winner/loser" declarations, NO scoreboards.
"""

import hashlib
import json
import os
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.parse_report import PARSER_SCHEMA_VERSION, PARSER_VERSION
from scripts.research_periods import load_research_periods

AUDITOR_VERSION = "1.0.0"
REPRODUCIBILITY_VERSION = "1.0.0"

# Explicit Reproducibility Status Codes
REPRODUCIBLE_IDENTITY = "REPRODUCIBLE_IDENTITY"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
CANDIDATE_HASH_MISMATCH = "CANDIDATE_HASH_MISMATCH"
DATASET_MISMATCH = "DATASET_MISMATCH"
BACKTEST_CONFIGURATION_MISMATCH = "BACKTEST_CONFIGURATION_MISMATCH"
RESEARCH_CONFIGURATION_CHANGED = "RESEARCH_CONFIGURATION_CHANGED"
APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
INVALID_DATASET = "INVALID_DATASET"
DATASET_OVERLAP = "DATASET_OVERLAP"
CANDIDATE_NOT_FOUND = "CANDIDATE_NOT_FOUND"
EXPERIMENT_NOT_FOUND = "EXPERIMENT_NOT_FOUND"

# Comparator Status Codes
MATCH = "MATCH"
MISMATCH = "MISMATCH"
METRIC_DIFFERENCE_DETECTED = "METRIC_DIFFERENCE_DETECTED"
UNCOMPARABLE = "UNCOMPARABLE"

# Non-Sensitive Keys Allowed / Keys to Strip for Fingerprinting
VOLATILE_KEYS = {
    "timestamp",
    "created_at",
    "parsed_at",
    "updated_at",
    "execution_time",
    "runtime_ms",
    "process_id",
    "pid",
    "report_file",
    "report_path",
    "output_path",
    "log_file",
    "temp_path",
}

SECRET_KEYS = {
    "password",
    "pass",
    "token",
    "secret",
    "api_key",
    "account",
    "credentials",
    "login",
}


def calculate_sha256_bytes(content: bytes) -> str:
    """Calculates SHA-256 hash of raw bytes."""
    return hashlib.sha256(content).hexdigest()


def calculate_sha256_file(file_path: Path) -> Optional[str]:
    """Calculates SHA-256 hash of a file if it exists."""
    if not file_path.is_file():
        return None
    try:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()
    except Exception:
        return None


def sanitize_dict_for_fingerprint(data: Any) -> Any:
    """
    Recursively strips volatile fields (timestamps, process IDs, file paths)
    and sensitive keys (credentials) from a dict/list for canonical fingerprinting.
    """
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            key_str = str(key).lower()
            if key_str in VOLATILE_KEYS or any(sec in key_str for sec in SECRET_KEYS):
                continue
            cleaned[key] = sanitize_dict_for_fingerprint(value)
        return cleaned
    elif isinstance(data, list):
        return [sanitize_dict_for_fingerprint(item) for item in data]
    elif isinstance(data, float):
        return round(data, 6)
    else:
        return data


def canonicalize_json(data: Any) -> str:
    """
    Produces a canonical, deterministic JSON string representation with sorted keys.
    """
    sanitized = sanitize_dict_for_fingerprint(data)
    return json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def calculate_configuration_fingerprint(config_dict: Dict[str, Any]) -> str:
    """
    Calculates deterministic SHA-256 hash for relevant experiment/tester configuration.
    """
    canonical_str = canonicalize_json(config_dict)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def calculate_research_periods_fingerprint(periods_config: Optional[Dict[str, Any]] = None, config_path: Optional[Path] = None) -> str:
    """
    Calculates deterministic SHA-256 hash for frozen research-periods configuration.
    """
    if periods_config is None:
        periods_config = load_research_periods(config_path)
    canonical_str = canonicalize_json(periods_config)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def calculate_experiment_identity_fingerprint(
    candidate_source_sha256: str,
    candidate_binary_sha256: str,
    config_hash: str,
    dataset_partition: str,
    dataset_from: str,
    dataset_to: str,
    symbol: str,
    timeframe: str,
    model: Any,
    evaluation_type: str = "training",
) -> str:
    """
    Calculates deterministic SHA-256 fingerprint for logical experiment identity.
    Two executions under identical declared conditions will yield the EXACT same fingerprint.
    """
    identity_payload = {
        "candidate_source_sha256": str(candidate_source_sha256).strip().lower(),
        "candidate_binary_sha256": str(candidate_binary_sha256).strip().lower(),
        "config_hash": str(config_hash).strip().lower(),
        "dataset_partition": str(dataset_partition).strip().lower(),
        "dataset_from": str(dataset_from).strip(),
        "dataset_to": str(dataset_to).strip(),
        "symbol": str(symbol).strip().upper(),
        "timeframe": str(timeframe).strip().upper(),
        "model": str(model).strip(),
        "evaluation_type": str(evaluation_type).strip().lower(),
    }
    canonical_str = json.dumps(identity_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def get_git_commit(project_root: Optional[Path] = None) -> Optional[str]:
    """Returns current Git commit hash if in a git repo."""
    root = Path(project_root) if project_root else PROJECT_ROOT
    try:
        import subprocess

        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return None


def capture_environment_metadata(project_root: Optional[Path] = None) -> Dict[str, Any]:
    """
    Captures non-sensitive environment metadata for reproducibility auditing.
    NO secrets, credentials, tokens, or account details are collected.
    """
    root = Path(project_root) if project_root else PROJECT_ROOT
    cfg_file = root / "config.json"
    cfg_hash = calculate_sha256_file(cfg_file)

    terminal_path = None
    terminal_build = None
    if cfg_file.is_file():
        try:
            cfg_data = json.loads(cfg_file.read_text(encoding="utf-8"))
            terminal_path = cfg_data.get("mt5_path")
            terminal_build = cfg_data.get("terminal_build") or "detected_at_runtime"
        except Exception:
            pass

    return {
        "operating_system": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python_version": sys.version.split()[0],
        "project_version": "1.0.0",
        "mt5_terminal_build": terminal_build or "unknown",
        "terminal_executable_path": terminal_path or "unspecified",
        "parser_version": PARSER_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "reproducibility_version": REPRODUCIBILITY_VERSION,
        "git_commit": get_git_commit(root),
        "project_config_hash": cfg_hash,
    }


def create_reproducibility_record(
    experiment_id: str,
    candidate_id: str,
    hypothesis_id: str,
    plan_id: str,
    evaluation_type: str,
    dataset_partition: str,
    dataset_from: str,
    dataset_to: str,
    symbol: str,
    timeframe: str,
    model: Any,
    deposit: Any,
    currency: str,
    leverage: str,
    candidate_source_sha256: str,
    candidate_binary_sha256: str,
    relevant_configuration_hash: str,
    research_periods_configuration_hash: str,
    experiment_metadata_hash: Optional[str] = None,
    training_experiment_id: Optional[str] = None,
    repeat_of_experiment_id: Optional[str] = None,
    environment_metadata: Optional[Dict[str, Any]] = None,
    reproducibility_status: str = REPRODUCIBLE_IDENTITY,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates standard Phase 15 Reproducibility Record dictionary.
    """
    env_meta = environment_metadata or capture_environment_metadata()
    ts = timestamp or datetime.now().astimezone().isoformat()

    identity_fp = calculate_experiment_identity_fingerprint(
        candidate_source_sha256=candidate_source_sha256,
        candidate_binary_sha256=candidate_binary_sha256,
        config_hash=relevant_configuration_hash,
        dataset_partition=dataset_partition,
        dataset_from=dataset_from,
        dataset_to=dataset_to,
        symbol=symbol,
        timeframe=timeframe,
        model=model,
        evaluation_type=evaluation_type,
    )

    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "candidate_id": candidate_id,
        "hypothesis_id": hypothesis_id,
        "plan_id": plan_id,
        "training_experiment_id": training_experiment_id,
        "repeat_of_experiment_id": repeat_of_experiment_id,
        "evaluation_type": evaluation_type,
        "dataset_partition": dataset_partition,
        "dataset_from": dataset_from,
        "dataset_to": dataset_to,
        "symbol": symbol,
        "timeframe": timeframe,
        "model": model,
        "deposit": deposit,
        "currency": currency,
        "leverage": leverage,
        "candidate_source_sha256": candidate_source_sha256,
        "candidate_binary_sha256": candidate_binary_sha256,
        "relevant_configuration_hash": relevant_configuration_hash,
        "research_periods_configuration_hash": research_periods_configuration_hash,
        "experiment_metadata_hash": experiment_metadata_hash,
        "experiment_identity_fingerprint": identity_fp,
        "environment_metadata": env_meta,
        "parser_version": PARSER_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "timestamp": ts,
        "reproducibility_status": reproducibility_status,
    }


def verify_repeat_execution_prerequisites(
    baseline_exp_id: str,
    candidate_id: str,
    experiments_dir: Optional[Path] = None,
    candidates_dir: Optional[Path] = None,
    plans_dir: Optional[Path] = None,
    research_periods_path: Optional[Path] = None,
) -> Tuple[bool, str, List[str], Dict[str, Any]]:
    """
    Pre-execution verification for repeat runs.
    Checks that candidate exists, source/binary SHA matches baseline experiment,
    dataset partition and dates match, symbol/timeframe/model match, backtest config matches,
    and research-periods configuration has not changed.

    Returns (is_valid, status_code, issues_list, baseline_metadata_dict).
    """
    exp_dir = Path(experiments_dir) if experiments_dir else PROJECT_ROOT / "experiments"
    cand_dir = Path(candidates_dir) if candidates_dir else PROJECT_ROOT / "developer" / "candidates"
    p_dir = Path(plans_dir) if plans_dir else PROJECT_ROOT / "research" / "plans"
    rp_path = Path(research_periods_path) if research_periods_path else PROJECT_ROOT / "config" / "research_periods.json"

    issues: List[str] = []

    # 1. Check baseline experiment directory and metadata
    base_exp_dir = exp_dir / baseline_exp_id
    if not base_exp_dir.is_dir():
        issues.append(f"Baseline experiment '{baseline_exp_id}' does not exist.")
        return False, EXPERIMENT_NOT_FOUND, issues, {}

    base_meta_file = base_exp_dir / "metadata.json"
    if not base_meta_file.is_file():
        issues.append(f"Baseline experiment '{baseline_exp_id}' missing metadata.json.")
        return False, EXPERIMENT_NOT_FOUND, issues, {}

    try:
        base_meta = json.loads(base_meta_file.read_text(encoding="utf-8"))
    except Exception as e:
        issues.append(f"Baseline experiment metadata unparseable: {str(e)}")
        return False, EXPERIMENT_NOT_FOUND, issues, {}

    # 2. Candidate existence
    cand_path = cand_dir / candidate_id
    if not cand_path.is_dir():
        issues.append(f"Candidate directory '{candidate_id}' does not exist.")
        return False, CANDIDATE_NOT_FOUND, issues, base_meta

    src_after = cand_path / "source_after.mq5"
    bin_after = cand_path / "source_after.ex5"
    if not src_after.is_file() or not bin_after.is_file():
        issues.append(f"Candidate source or binary missing in '{candidate_id}'.")
        return False, CANDIDATE_HASH_MISMATCH, issues, base_meta

    curr_src_sha = calculate_sha256_file(src_after)
    curr_bin_sha = calculate_sha256_file(bin_after)

    recorded_src_sha = (
        base_meta.get("candidate_source_sha256")
        or base_meta.get("source_after_sha256")
        or base_meta.get("reproducibility", {}).get("candidate_source_sha256")
    )
    recorded_bin_sha = (
        base_meta.get("candidate_binary_sha256")
        or base_meta.get("candidate_ex5_sha256")
        or base_meta.get("source_after_ex5_sha256")
        or base_meta.get("reproducibility", {}).get("candidate_binary_sha256")
    )

    if recorded_src_sha and curr_src_sha != recorded_src_sha:
        issues.append(f"Candidate source hash mismatch: current '{curr_src_sha}', recorded '{recorded_src_sha}'.")
        return False, CANDIDATE_HASH_MISMATCH, issues, base_meta

    if recorded_bin_sha and curr_bin_sha != recorded_bin_sha:
        issues.append(f"Candidate binary hash mismatch: current '{curr_bin_sha}', recorded '{recorded_bin_sha}'.")
        return False, CANDIDATE_HASH_MISMATCH, issues, base_meta

    # 3. Check Research Periods configuration match
    current_rp_hash = calculate_research_periods_fingerprint(config_path=rp_path)
    recorded_rp_hash = base_meta.get("research_periods_configuration_hash") or base_meta.get("reproducibility", {}).get("research_periods_configuration_hash")

    if recorded_rp_hash and current_rp_hash != recorded_rp_hash:
        issues.append(f"Research periods configuration changed: current '{current_rp_hash}', recorded '{recorded_rp_hash}'.")
        return False, RESEARCH_CONFIGURATION_CHANGED, issues, base_meta

    # All pre-flight checks passed
    return True, REPRODUCIBLE_IDENTITY, [], base_meta


def compare_experiments_reproducibility(
    exp_id_1: str,
    exp_id_2: str,
    experiments_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Compares original experiment (exp_id_1) against repeat execution (exp_id_2).
    Evaluates identity, configuration, dataset, environment, and metric differences.
    Returns structured comparison dictionary without subjective rankings or scores.
    """
    exp_dir = Path(experiments_dir) if experiments_dir else PROJECT_ROOT / "experiments"
    dir_1 = exp_dir / exp_id_1
    dir_2 = exp_dir / exp_id_2

    if not dir_1.is_dir() or not dir_2.is_dir():
        return {
            "status": UNCOMPARABLE,
            "reason": f"One or both experiment directories missing ({exp_id_1}, {exp_id_2}).",
            "differences": {},
        }

    meta_1_file = dir_1 / "metadata.json"
    meta_2_file = dir_2 / "metadata.json"
    metrics_1_file = dir_1 / "metrics.json"
    metrics_2_file = dir_2 / "metrics.json"

    if not meta_1_file.is_file() or not meta_2_file.is_file():
        return {
            "status": UNCOMPARABLE,
            "reason": "One or both experiments missing metadata.json.",
            "differences": {},
        }

    meta1 = json.loads(meta_1_file.read_text(encoding="utf-8"))
    meta2 = json.loads(meta_2_file.read_text(encoding="utf-8"))
    metrics1 = json.loads(metrics_1_file.read_text(encoding="utf-8")) if metrics_1_file.is_file() else {}
    metrics2 = json.loads(metrics_2_file.read_text(encoding="utf-8")) if metrics_2_file.is_file() else {}

    identity_diffs = []
    config_diffs = []
    metric_diffs = []

    # Identity check
    cand1 = meta1.get("candidate_id")
    cand2 = meta2.get("candidate_id")
    if cand1 != cand2:
        identity_diffs.append(f"Candidate ID mismatch: {cand1} vs {cand2}")

    src_hash1 = meta1.get("candidate_source_sha256") or meta1.get("source_after_sha256")
    src_hash2 = meta2.get("candidate_source_sha256") or meta2.get("source_after_sha256")
    if src_hash1 != src_hash2:
        identity_diffs.append(f"Candidate source hash mismatch: {src_hash1} vs {src_hash2}")

    bin_hash1 = meta1.get("candidate_binary_sha256") or meta1.get("candidate_ex5_sha256") or meta1.get("source_after_ex5_sha256")
    bin_hash2 = meta2.get("candidate_binary_sha256") or meta2.get("candidate_ex5_sha256") or meta2.get("source_after_ex5_sha256")
    if bin_hash1 != bin_hash2:
        identity_diffs.append(f"Candidate binary hash mismatch: {bin_hash1} vs {bin_hash2}")

    # Config check
    for key in ["symbol", "timeframe", "model", "deposit", "currency", "leverage"]:
        val1 = meta1.get(key) or meta1.get("backtest_config", {}).get(key)
        val2 = meta2.get(key) or meta2.get("backtest_config", {}).get(key)
        if val1 != val2:
            config_diffs.append(f"{key} mismatch: '{val1}' vs '{val2}'")

    date_from_1 = meta1.get("from") or meta1.get("dataset_from")
    date_from_2 = meta2.get("from") or meta2.get("dataset_from")
    if date_from_1 != date_from_2:
        config_diffs.append(f"Dataset start date mismatch: '{date_from_1}' vs '{date_from_2}'")

    date_to_1 = meta1.get("to") or meta1.get("dataset_to")
    date_to_2 = meta2.get("to") or meta2.get("dataset_to")
    if date_to_1 != date_to_2:
        config_diffs.append(f"Dataset end date mismatch: '{date_to_1}' vs '{date_to_2}'")

    # Metrics comparison
    m1 = metrics1.get("metrics", {})
    m2 = metrics2.get("metrics", {})

    compare_metric_keys = [
        "bars",
        "ticks",
        "total_trades",
        "total_net_profit",
        "profit_factor",
        "expected_payoff",
        "history_quality_percent",
    ]

    metric_deltas = {}
    for mk in compare_metric_keys:
        v1 = m1.get(mk)
        v2 = m2.get(mk)
        if v1 != v2:
            delta = None
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                delta = round(v2 - v1, 6)
            metric_deltas[mk] = {"original": v1, "repeat": v2, "delta": delta}
            metric_diffs.append(f"Metric '{mk}' difference: original={v1}, repeat={v2}")

    if identity_diffs or config_diffs:
        overall_status = MISMATCH
    elif metric_diffs:
        overall_status = METRIC_DIFFERENCE_DETECTED
    else:
        overall_status = MATCH

    return {
        "status": overall_status,
        "experiment_1": exp_id_1,
        "experiment_2": exp_id_2,
        "identity_differences": identity_diffs,
        "config_differences": config_diffs,
        "metric_differences": metric_diffs,
        "metric_deltas": metric_deltas,
    }


def verify_experiment_immutability(
    exp_id: str,
    expected_hashes: Dict[str, str],
    experiments_dir: Optional[Path] = None,
) -> Tuple[bool, List[str]]:
    """
    Verifies that files in experiment EXP-XXXX have not been altered or mutated.
    """
    exp_dir = Path(experiments_dir) if experiments_dir else PROJECT_ROOT / "experiments"
    target_dir = exp_dir / exp_id
    issues = []

    if not target_dir.is_dir():
        return False, [f"Experiment directory '{exp_id}' does not exist."]

    for rel_file, exp_hash in expected_hashes.items():
        file_path = target_dir / rel_file
        if not file_path.is_file():
            issues.append(f"Expected file '{rel_file}' is missing from experiment '{exp_id}'.")
            continue
        calc_hash = calculate_sha256_file(file_path)
        if calc_hash != exp_hash:
            issues.append(
                f"File '{rel_file}' in experiment '{exp_id}' was mutated! Calculated '{calc_hash}', expected '{exp_hash}'."
            )

    return len(issues) == 0, issues
