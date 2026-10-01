"""
AI EA Lab - Candidate Backtest Runner & Verification Pipeline (Phase 9)

Orchestrates:
Candidate Verification -> Port Check -> Candidate Staging -> MT5 Strategy Tester
-> Report Verification -> Parser -> Experiment Creation (EXP-XXXX) -> Manifest Update.

Enforces:
1. Strict Candidate Provenance (HYP-XXXX -> PLAN-XXXX -> CAND-XXXX -> EXP-XXXX).
2. Candidate Isolation (Stages into MQL5/Experts/Candidates/ without touching baseline EAs).
3. Zero-Trade vs Zero-Data distinction.
4. Anti-contamination Report Identity Verification.
5. Explicit Error States and Deterministic Execution.
6. Zero Live Trading, Zero Broker Orders, Zero Credential Manipulation.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest import check_port_conflict, load_config
from scripts.candidate_sync import cleanup_staged_candidate, stage_candidate_binary
from scripts.candidate_verifier import (
    calculate_sha256,
    verify_candidate,
    verify_candidate_for_validation,
)
from scripts.parse_report import parse_report
from scripts.research_periods import (
    is_periods_configured,
    load_research_periods,
    parse_date,
    resolve_dataset_partition,
)
from scripts.run_experiment import get_git_commit, get_next_experiment_id
from scripts.reproducibility import (
    APPROVAL_REQUIRED,
    BACKTEST_CONFIGURATION_MISMATCH,
    CANDIDATE_HASH_MISMATCH,
    DATASET_MISMATCH,
    EXPERIMENT_NOT_FOUND,
    IDENTITY_MISMATCH,
    REPRODUCIBLE_IDENTITY,
    RESEARCH_CONFIGURATION_CHANGED,
    calculate_configuration_fingerprint,
    calculate_experiment_identity_fingerprint,
    calculate_research_periods_fingerprint,
    capture_environment_metadata,
    create_reproducibility_record,
    verify_experiment_immutability,
    verify_repeat_execution_prerequisites,
)

CANDIDATES_DIR = PROJECT_ROOT / "developer" / "candidates"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
CONFIG_PATH = PROJECT_ROOT / "config.json"
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"

# Explicit Status Codes
STATUS_SUCCESS = "SUCCESS"
STATUS_READY = "READY"
STATUS_CANDIDATE_NOT_FOUND = "CANDIDATE_NOT_FOUND"
STATUS_CANDIDATE_INVALID = "CANDIDATE_INVALID"
STATUS_PROVENANCE_INVALID = "PROVENANCE_INVALID"
STATUS_BINARY_MISSING = "BINARY_MISSING"
STATUS_BINARY_INVALID = "BINARY_INVALID"
STATUS_DATASET_NOT_CONFIGURED = "DATASET_NOT_CONFIGURED"
STATUS_DATASET_MISSING = "DATASET_MISSING"
STATUS_INVALID_DATASET = "INVALID_DATASET"
STATUS_DATASET_MISMATCH = "DATASET_MISMATCH"
STATUS_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
STATUS_CANDIDATE_HASH_MISMATCH = "CANDIDATE_HASH_MISMATCH"
STATUS_DATASET_OVERLAP = "DATASET_OVERLAP"
STATUS_TESTER_PORT_CONFLICT = "TESTER_PORT_CONFLICT"
STATUS_MT5_LAUNCH_FAILED = "MT5_LAUNCH_FAILED"
STATUS_TESTER_TIMEOUT = "TESTER_TIMEOUT"
STATUS_TESTER_FAILED = "TESTER_FAILED"
STATUS_REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
STATUS_REPORT_EMPTY = "REPORT_EMPTY"
STATUS_REPORT_INVALID = "REPORT_INVALID"
STATUS_REPORT_IDENTITY_MISMATCH = "REPORT_IDENTITY_MISMATCH"
STATUS_PARSER_FAILED = "PARSER_FAILED"
STATUS_EXPERIMENT_CREATION_FAILED = "EXPERIMENT_CREATION_FAILED"


def resolve_dataset_dates(
    plan: Dict[str, Any],
    research_periods_path: Path = RESEARCH_PERIODS_PATH,
    allow_unconfigured_dates: bool = False,
) -> Tuple[bool, Optional[str], Optional[str], Optional[str], str]:
    """
    Resolves backtest date window against research periods configuration.
    Enforces Phase 13 dataset requirements:
    - Plan must specify dataset partition. Missing dataset -> DATASET_MISSING.
    - Invalid partition -> INVALID_DATASET.
    - Resolves dates from research_periods.json.
    - Detects plan dataset date range mismatch against resolved partition dates -> DATASET_MISMATCH.
    """
    dataset_spec = plan.get("dataset")
    if not dataset_spec:
        return False, None, None, None, STATUS_DATASET_MISSING

    if isinstance(dataset_spec, dict):
        raw_partition = dataset_spec.get("partition") or dataset_spec.get("type")
        plan_from = dataset_spec.get("from")
        plan_to = dataset_spec.get("to")
    elif isinstance(dataset_spec, str):
        raw_partition = dataset_spec
        plan_from = None
        plan_to = None
    else:
        return False, None, None, None, STATUS_DATASET_MISSING

    if not raw_partition:
        return False, None, None, None, STATUS_DATASET_MISSING

    success, norm_partition, p_from, p_to, status_code = resolve_dataset_partition(
        raw_partition, config_path=research_periods_path
    )

    if not success:
        if status_code == "UNCONFIGURED" and allow_unconfigured_dates and plan_from and plan_to:
            return True, norm_partition or "training", plan_from, plan_to, "UNCONFIGURED_FALLBACK"
        if status_code == "INVALID_DATASET":
            return False, norm_partition, None, None, STATUS_INVALID_DATASET
        if status_code == "DATASET_MISSING":
            return False, None, None, None, STATUS_DATASET_MISSING
        return False, norm_partition or "training", None, None, STATUS_DATASET_NOT_CONFIGURED

    # Dataset Mismatch Protection: if plan explicitly provides dates, compare with resolved partition
    if plan_from and parse_date(plan_from) and p_from and parse_date(plan_from) != parse_date(p_from):
        return False, norm_partition, p_from, p_to, STATUS_DATASET_MISMATCH
    if plan_to and parse_date(plan_to) and p_to and parse_date(plan_to) != parse_date(p_to):
        return False, norm_partition, p_from, p_to, STATUS_DATASET_MISMATCH

    return True, norm_partition, p_from, p_to, "CONFIGURED"


def generate_candidate_tester_config(
    candidate_id: str,
    expert_param: str,
    config: Dict[str, Any],
    from_date: str,
    to_date: str,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    model: Optional[int] = None,
    output_dir: Optional[Path] = None,
) -> Tuple[Path, str]:
    """
    Generates backtest.ini configuration for Strategy Tester isolated to candidate.
    Returns (tester_config_path, report_filename).
    """
    out_dir = output_dir or (PROJECT_ROOT / "tester" / "configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    tester_config_path = out_dir / f"backtest_{candidate_id}.ini"

    backtest_cfg = config.get("backtest", {})
    sym = symbol or backtest_cfg.get("symbol", "GBPUSD")
    tf = timeframe or backtest_cfg.get("timeframe", "M15")
    mdl = model if model is not None else backtest_cfg.get("model", 1)
    deposit = backtest_cfg.get("deposit", 10000)
    currency = backtest_cfg.get("currency", "USD")
    leverage = backtest_cfg.get("leverage", "1:100")

    report_name = f"{candidate_id}_report.htm"

    ini_content = f"""[Tester]
Expert={expert_param}
Symbol={sym}
Period={tf}
Model={mdl}
FromDate={from_date}
ToDate={to_date}
Deposit={deposit}
Currency={currency}
Leverage={leverage}
Optimization=0
Report={report_name}
ReplaceReport=1
ShutdownTerminal=1
"""
    tester_config_path.write_text(ini_content, encoding="utf-8")
    return tester_config_path, report_name


def verify_candidate_report(
    report_path: Path,
    expected_candidate_id: str,
    expected_symbol: str,
    expected_timeframe: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Verifies the generated HTML report exists, has non-zero size,
    and confirms the tested expert strictly matches the requested candidate.
    Distinguishes zero-trade vs zero-data.
    Returns (is_valid, status, extracted_info).
    """
    info: Dict[str, Any] = {
        "report_path": str(report_path),
        "file_size": 0,
        "expert": None,
        "symbol": None,
        "period": None,
        "bars": 0,
        "ticks": 0,
        "trades": 0,
        "test_executed": False,
    }

    if not report_path.is_file():
        return False, STATUS_REPORT_NOT_FOUND, info

    file_size = report_path.stat().st_size
    info["file_size"] = file_size
    if file_size == 0:
        return False, STATUS_REPORT_EMPTY, info

    raw_bytes = report_path.read_bytes()
    if raw_bytes.startswith(b"\xff\xfe") or b"\x00" in raw_bytes[:100]:
        content = raw_bytes.decode("utf-16le", errors="ignore")
    else:
        content = raw_bytes.decode("utf-8", errors="ignore")

    # Regex extractions from MT5 report HTML
    expert_match = re.search(r"Expert:\s*</td>\s*<td[^>]*><b>([^<]+)</b>", content, re.IGNORECASE)
    symbol_match = re.search(r"Symbol:\s*</td>\s*<td[^>]*><b>([^<]+)</b>", content, re.IGNORECASE)
    period_match = re.search(r"Period:\s*</td>\s*<td[^>]*><b>([^<]+)</b>", content, re.IGNORECASE)
    bars_match = re.search(r"Bars:\s*</td>\s*<td[^>]*><b>(\d+)</b>", content, re.IGNORECASE)
    ticks_match = re.search(r"Ticks:\s*</td>\s*<td[^>]*><b>(\d+)</b>", content, re.IGNORECASE)
    trades_match = re.search(r"Total Trades:\s*</td>\s*<td[^>]*><b>(\d+)</b>", content, re.IGNORECASE)

    if expert_match:
        info["expert"] = expert_match.group(1).strip()
    if symbol_match:
        info["symbol"] = symbol_match.group(1).strip()
    if period_match:
        info["period"] = period_match.group(1).strip()
    if bars_match:
        info["bars"] = int(bars_match.group(1))
    if ticks_match:
        info["ticks"] = int(ticks_match.group(1))
    if trades_match:
        info["trades"] = int(trades_match.group(1))

    # Anti-contamination: Verify tested EA identity
    tested_expert = info.get("expert") or ""
    clean_expert = tested_expert.replace("Candidates\\", "").replace("Candidates/", "").replace(".ex5", "").strip()
    if clean_expert != expected_candidate_id and expected_candidate_id not in tested_expert:
        return False, STATUS_REPORT_IDENTITY_MISMATCH, info

    # Zero-data check: Strategy tester failed to process any market bars or ticks
    if info["bars"] == 0 and info["ticks"] == 0:
        return False, STATUS_REPORT_INVALID, info

    info["test_executed"] = True
    return True, STATUS_SUCCESS, info


def execute_candidate_backtest(
    candidate_id: str,
    dry_run: bool = False,
    verify_only: bool = False,
    timeout_seconds: int = 180,
    allow_unconfigured_dates: bool = False,
    note: Optional[str] = None,
    candidates_dir: Path = CANDIDATES_DIR,
    plans_dir: Path = PLANS_DIR,
    experiments_dir: Path = EXPERIMENTS_DIR,
    config_path: Path = CONFIG_PATH,
    research_periods_path: Path = RESEARCH_PERIODS_PATH,
    mt5_launcher=None,  # Optional mock launcher for isolated unit tests
) -> Dict[str, Any]:
    """
    Executes the candidate backtest pipeline.
    """
    candidates_dir = Path(candidates_dir)
    plans_dir = Path(plans_dir)
    experiments_dir = Path(experiments_dir)
    config_path = Path(config_path)

    result: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "plan_id": None,
        "hypothesis_id": None,
        "baseline_experiment": None,
        "status": "PENDING",
        "verification": {},
        "backtest": {},
        "experiment": {
            "created": False,
            "experiment_id": None,
            "directory": None,
        },
        "dry_run": dry_run,
        "verify_only": verify_only,
        "error": None,
    }

    # 1. Candidate Pre-flight Verification
    verif = verify_candidate(
        candidate_id,
        candidates_dir=candidates_dir,
        plans_dir=plans_dir,
        experiments_dir=experiments_dir,
    )
    result["verification"] = {
        "verified": verif["verified"],
        "source": verif["source_verified"],
        "binary": verif["binary_verified"],
        "compile": verif["compile_verified"],
        "provenance": verif["provenance_verified"],
        "hashes": verif["hashes"],
        "issues": verif["issues"],
    }

    if not verif["verified"]:
        result["status"] = verif["status"]
        result["error"] = f"Candidate verification failed: {'; '.join(verif['issues'])}"
        return result

    cand_meta = verif["metadata"]
    plan = verif["plan"]
    result["plan_id"] = cand_meta.get("plan_id")
    result["hypothesis_id"] = cand_meta.get("hypothesis_id")
    result["baseline_experiment"] = cand_meta.get("baseline_experiment")

    # If verify-only mode requested, stop here with success
    if verify_only:
        result["status"] = STATUS_READY
        return result

    # 2. Dataset & Date Window Resolution
    has_plan_dates = (
        bool(plan.get("dataset", {}).get("from") and plan.get("dataset", {}).get("to"))
        if isinstance(plan.get("dataset"), dict)
        else False
    )
    dates_ok, dataset_type, from_date, to_date, dates_status = resolve_dataset_dates(
        plan,
        research_periods_path=research_periods_path,
        allow_unconfigured_dates=allow_unconfigured_dates or has_plan_dates,
    )
    if not dates_ok:
        result["status"] = dates_status
        if dates_status == STATUS_DATASET_MISSING:
            result["error"] = "Plan does not specify a dataset partition."
        elif dates_status == STATUS_INVALID_DATASET:
            result["error"] = f"Invalid dataset partition '{dataset_type}' specified in plan."
        elif dates_status == STATUS_DATASET_MISMATCH:
            result["error"] = f"Plan date range does not match configured research period for partition '{dataset_type}'."
        else:
            result["error"] = (
                f"Dataset type '{dataset_type}' is unconfigured in {research_periods_path.name}. "
                "Define actual dates before production backtesting or pass --allow-unconfigured-dates."
            )
        return result

    # 3. Load System Configuration
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        result["status"] = STATUS_CANDIDATE_INVALID
        result["error"] = f"Failed to load config.json: {str(e)}"
        return result

    mt5_data = Path(config.get("mt5_data", ""))
    terminal = Path(config.get("mt5_terminal", ""))
    sym = plan.get("baseline", {}).get("symbol") or config.get("backtest", {}).get("symbol", "GBPUSD")
    tf = plan.get("baseline", {}).get("timeframe") or config.get("backtest", {}).get("timeframe", "M15")
    mdl = config.get("backtest", {}).get("model", 1)

    result["backtest"]["configuration"] = {
        "dataset": dataset_type,
        "symbol": sym,
        "timeframe": tf,
        "model": mdl,
        "from": from_date,
        "to": to_date,
    }

    # 4. Dry-Run Handling
    if dry_run:
        result["status"] = STATUS_READY
        result["backtest"]["status"] = "dry_run"
        result["backtest"]["expected_binary"] = verif["binary_path"]
        result["backtest"]["expected_report"] = f"{candidate_id}_report.htm"
        return result

    # 5. Port 3000 Conflict Check
    if not mt5_launcher and not check_port_conflict():
        result["status"] = STATUS_TESTER_PORT_CONFLICT
        result["error"] = "Local port 3000 is occupied; MT5 tester core cannot bind."
        return result

    # 6. Candidate Binary Synchronization / Isolation
    sync_record = stage_candidate_binary(
        candidate_id=candidate_id,
        source_binary_path=Path(verif["binary_path"]),
        mt5_data_dir=mt5_data,
    )
    result["backtest"]["sync"] = sync_record
    if not sync_record.get("verified"):
        result["status"] = STATUS_BINARY_INVALID
        result["error"] = f"Candidate staging failed: {sync_record.get('error')}"
        return result

    # 7. Generate Tester Configuration (backtest_{candidate_id}.ini)
    tester_config_path, report_name = generate_candidate_tester_config(
        candidate_id=candidate_id,
        expert_param=sync_record["expert_param"],
        config=config,
        from_date=from_date,
        to_date=to_date,
        symbol=sym,
        timeframe=tf,
        model=mdl,
    )
    mt5_report_path = mt5_data / report_name

    # Clear any stale report or chart assets before MT5 execution
    if mt5_report_path.exists():
        try:
            mt5_report_path.unlink()
        except Exception:
            pass
    stem = mt5_report_path.stem
    for asset in mt5_data.glob(f"{stem}*.png"):
        try:
            asset.unlink()
        except Exception:
            pass

    # 8. Strategy Tester Execution
    start_time = datetime.now().astimezone().isoformat()
    cmd = [str(terminal), f"/config:{tester_config_path}"]

    if mt5_launcher:
        # Use provided launcher (for isolated tests)
        launch_res = mt5_launcher(cmd, timeout_seconds)
        proc_exit = launch_res.get("exit_code", 0)
        proc_timeout = launch_res.get("timeout", False)
    else:
        # Real MT5 subprocess launch
        try:
            proc = subprocess.Popen(cmd)
            t0 = time.time()
            proc_timeout = False
            while proc.poll() is None:
                if time.time() - t0 > timeout_seconds:
                    proc.kill()
                    proc_timeout = True
                    break
                time.sleep(1)
            proc_exit = proc.returncode if not proc_timeout else -1
        except Exception as e:
            result["status"] = STATUS_MT5_LAUNCH_FAILED
            result["error"] = f"Failed to start MT5 process: {str(e)}"
            return result

    end_time = datetime.now().astimezone().isoformat()
    result["backtest"]["execution"] = {
        "start_time": start_time,
        "end_time": end_time,
        "exit_code": proc_exit,
        "timeout": proc_timeout,
    }

    if proc_timeout:
        result["status"] = STATUS_TESTER_TIMEOUT
        result["error"] = f"MT5 Strategy Tester timed out after {timeout_seconds} seconds."
        return result

    if proc_exit != 0 and proc_exit is not None:
        result["status"] = STATUS_TESTER_FAILED
        result["error"] = f"MT5 Strategy Tester exited with non-zero code {proc_exit}."
        return result

    # 9. Report Verification & Anti-Contamination Identity Check
    is_rep_valid, rep_status, rep_info = verify_candidate_report(
        mt5_report_path,
        expected_candidate_id=candidate_id,
        expected_symbol=sym,
        expected_timeframe=tf,
    )
    result["backtest"]["report_info"] = rep_info

    if not is_rep_valid:
        result["status"] = rep_status
        result["error"] = f"Report verification failed: {rep_status}"
        return result

    # Copy report & chart assets to tester/reports
    project_reports_dir = PROJECT_ROOT / "tester" / "reports"
    project_reports_dir.mkdir(parents=True, exist_ok=True)
    project_rep = project_reports_dir / report_name
    shutil.copy2(mt5_report_path, project_rep)

    stem = mt5_report_path.stem
    for asset in mt5_data.glob(f"{stem}*.png"):
        shutil.copy2(asset, project_reports_dir / asset.name)

    # 10. Report Parsing
    try:
        parsed_result = parse_report(project_rep)
    except Exception as e:
        result["status"] = STATUS_PARSER_FAILED
        result["error"] = f"Failed to parse MT5 report metrics: {str(e)}"
        return result

    # 11. Create Immutable Experiment Archive (EXP-XXXX)
    try:
        exp_id = get_next_experiment_id(experiments_dir)
        exp_dir = experiments_dir / exp_id
        charts_dir = exp_dir / "charts"

        exp_dir.mkdir(parents=True, exist_ok=False)
        charts_dir.mkdir(parents=True, exist_ok=True)

        # Copy HTML report
        shutil.copy2(project_rep, exp_dir / "report.htm")

        # Copy chart images
        chart_files = []
        for asset in project_reports_dir.glob(f"{stem}*.png"):
            dest_asset = charts_dir / asset.name
            shutil.copy2(asset, dest_asset)
            chart_files.append(f"charts/{asset.name}")

        # Save metrics.json
        (exp_dir / "metrics.json").write_text(
            json.dumps(parsed_result, indent=2), encoding="utf-8"
        )

        backtest_cfg = {
            "symbol": sym,
            "timeframe": tf,
            "model": mdl,
            "from": from_date,
            "to": to_date,
            "deposit": config.get("backtest", {}).get("deposit", 10000),
            "currency": config.get("backtest", {}).get("currency", "USD"),
            "leverage": config.get("backtest", {}).get("leverage", "1:100"),
            "inputs": parsed_result["settings"]["inputs"],
        }
        rel_config_hash = calculate_configuration_fingerprint(backtest_cfg)
        rp_config_hash = calculate_research_periods_fingerprint(config_path=research_periods_path)
        env_meta = capture_environment_metadata(PROJECT_ROOT)

        # Link training experiment ID for validation evaluation provenance
        training_exp_id = cand_meta.get("baseline_experiment") if dataset_type == "validation" else None

        repro_record = create_reproducibility_record(
            experiment_id=exp_id,
            candidate_id=candidate_id,
            hypothesis_id=cand_meta.get("hypothesis_id"),
            plan_id=cand_meta.get("plan_id"),
            training_experiment_id=training_exp_id,
            evaluation_type=dataset_type,
            dataset_partition=dataset_type,
            dataset_from=from_date,
            dataset_to=to_date,
            symbol=sym,
            timeframe=tf,
            model=mdl,
            deposit=config.get("backtest", {}).get("deposit", 10000),
            currency=config.get("backtest", {}).get("currency", "USD"),
            leverage=config.get("backtest", {}).get("leverage", "1:100"),
            candidate_source_sha256=verif["hashes"].get("source_after_sha256"),
            candidate_binary_sha256=verif["hashes"].get("source_after_ex5_sha256"),
            relevant_configuration_hash=rel_config_hash,
            research_periods_configuration_hash=rp_config_hash,
            environment_metadata=env_meta,
        )

        # Save metadata.json linking complete candidate provenance
        exp_metadata = {
            "experiment_id": exp_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "note": note,
            "candidate_id": candidate_id,
            "training_experiment_id": training_exp_id,
            "plan_id": cand_meta.get("plan_id"),
            "hypothesis_id": cand_meta.get("hypothesis_id"),
            "baseline_experiment": cand_meta.get("baseline_experiment"),
            "ea": cand_meta.get("ea"),
            "symbol": sym,
            "timeframe": tf,
            "from": from_date,
            "to": to_date,
            "dataset": {
                "partition": dataset_type,
                "from": from_date,
                "to": to_date,
                "source": "config/research_periods.json",
            },
            "report": "report.htm",
            "metrics": "metrics.json",
            "charts": chart_files,
            "candidate_source_sha256": verif["hashes"].get("source_after_sha256"),
            "candidate_ex5_sha256": verif["hashes"].get("source_after_ex5_sha256"),
            "relevant_configuration_hash": rel_config_hash,
            "research_periods_configuration_hash": rp_config_hash,
            "experiment_identity_fingerprint": repro_record["experiment_identity_fingerprint"],
            "reproducibility": repro_record,
            "backtest_config": backtest_cfg,
            "inputs": parsed_result["settings"]["inputs"],
            "tester_sync": sync_record,
            "git_commit": get_git_commit(PROJECT_ROOT),
            "parser_schema_version": parsed_result.get("schema_version", 1),
            "status": "COMPLETED",
        }

        (exp_dir / "metadata.json").write_text(
            json.dumps(exp_metadata, indent=2), encoding="utf-8"
        )
        (exp_dir / "reproducibility.json").write_text(
            json.dumps(repro_record, indent=2), encoding="utf-8"
        )

        result["experiment"]["created"] = True
        result["experiment"]["experiment_id"] = exp_id
        result["experiment"]["directory"] = str(exp_dir)
    except Exception as e:
        result["status"] = STATUS_EXPERIMENT_CREATION_FAILED
        result["error"] = f"Failed to create experiment archive: {str(e)}"
        return result

    # 12. Update Manifest Index & Auto-Ingest Memory
    try:
        from scripts.build_manifest import build_manifest
        build_manifest(quiet=True, experiments_dir=experiments_dir, output_path=experiments_dir / "manifest.json")
    except Exception:
        pass

    try:
        from scripts.memory import ingest_experiment
        ingest_experiment(exp_id, experiments_dir=experiments_dir)
    except Exception:
        pass

    result["status"] = STATUS_SUCCESS
    return result



def format_human_readable_output(result: Dict[str, Any]) -> str:
    """Formats candidate runner output for console display."""
    cid = result.get("candidate_id", "UNKNOWN")
    pid = result.get("plan_id", "NONE")
    hid = result.get("hypothesis_id", "NONE")
    status = result.get("status", "UNKNOWN")

    lines = [
        "============================================================",
        "AI-EA-LAB -- CANDIDATE BACKTEST",
        "============================================================",
        f"Candidate: {cid}",
        f"Plan: {pid}",
        f"Hypothesis: {hid}",
    ]

    cfg = result.get("backtest", {}).get("configuration", {})
    if cfg:
        lines.append("")
        lines.append(f"Dataset: {cfg.get('dataset')}")
        lines.append(f"Symbol: {cfg.get('symbol')}")
        lines.append(f"Timeframe: {cfg.get('timeframe')}")
        lines.append(f"Model: {cfg.get('model')}")
        lines.append(f"Period: {cfg.get('from')} -> {cfg.get('to')}")

    verif = result.get("verification", {})
    lines.append("")
    lines.append(f"Verification: {'PASS' if verif.get('verified') else 'FAIL'}")
    if verif.get("issues"):
        for issue in verif["issues"]:
            lines.append(f"  - {issue}")

    exp = result.get("experiment", {})
    if exp.get("created"):
        lines.append("")
        lines.append(f"New Experiment: {exp.get('experiment_id')}")
        lines.append(f"Archive: {exp.get('directory')}")

    if result.get("error"):
        lines.append("")
        lines.append(f"Error:\n    {result['error']}")

    lines.append("")
    if result.get("dry_run"):
        lines.append("Status:\n    READY FOR BACKTEST (DRY RUN)")
    elif result.get("verify_only"):
        lines.append(f"Status:\n    {status} (VERIFY ONLY)")
    else:
        lines.append(f"Status:\n    {status}")
    lines.append("============================================================")

    return "\n".join(lines)


def execute_candidate_validation(
    candidate_id: str,
    training_experiment_id: str,
    plan_id: Optional[str] = None,
    validation_approval: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    verify_only: bool = False,
    timeout_seconds: int = 180,
    allow_unconfigured_dates: bool = False,
    note: Optional[str] = None,
    candidates_dir: Path = CANDIDATES_DIR,
    plans_dir: Path = PLANS_DIR,
    experiments_dir: Path = EXPERIMENTS_DIR,
    config_path: Path = CONFIG_PATH,
    research_periods_path: Path = RESEARCH_PERIODS_PATH,
    mt5_launcher=None,
) -> Dict[str, Any]:
    """
    Phase 14: Orchestrates independent out-of-sample VALIDATION evaluation for an approved candidate.
    Enforces:
    1. Explicit Validation Approval (halts if approval missing/pending/rejected).
    2. Candidate Hash Verification against Training Experiment (halts on hash mismatch).
    3. Strict VALIDATION partition resolution (2025.01.01 -> 2025.12.31).
    4. Dataset Non-Overlap Protection (validation dates must not overlap training or unseen).
    5. Immutability of Training Evidence (training experiment artifacts remain untouched).
    6. Complete Provenance Preservation in new experiment EXP-XXXX metadata.
    """
    candidates_dir = Path(candidates_dir)
    plans_dir = Path(plans_dir)
    experiments_dir = Path(experiments_dir)
    config_path = Path(config_path)
    research_periods_path = Path(research_periods_path)

    result: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "training_experiment_id": training_experiment_id,
        "plan_id": plan_id,
        "evaluation_type": "validation",
        "status": "PENDING",
        "verification": {},
        "backtest": {},
        "experiment": {
            "created": False,
            "experiment_id": None,
            "directory": None,
        },
        "dry_run": dry_run,
        "verify_only": verify_only,
        "error": None,
    }

    # 1. Enforce Explicit Validation Human Approval
    if not validation_approval or not isinstance(validation_approval, dict):
        if plan_id:
            p_file = plans_dir / f"{plan_id}.json"
            if p_file.is_file():
                try:
                    p_data = json.loads(p_file.read_text(encoding="utf-8"))
                    validation_approval = p_data.get("validation_approval") or p_data.get("approval")
                except Exception:
                    pass

    app_status = (
        str(validation_approval.get("status", "")).strip().lower()
        if isinstance(validation_approval, dict)
        else ""
    )
    if app_status != "approved":
        result["status"] = STATUS_APPROVAL_REQUIRED
        result["error"] = f"Validation execution halted: explicit human approval is required (status: '{app_status or 'missing'}')."
        return result

    # 2. Candidate & Training Experiment Integrity Verification
    verif = verify_candidate_for_validation(
        candidate_id=candidate_id,
        training_exp_id=training_experiment_id,
        candidates_dir=candidates_dir,
        experiments_dir=experiments_dir,
        plans_dir=plans_dir,
    )
    result["verification"] = {
        "verified": verif["verified"],
        "source": verif.get("source_verified", False),
        "binary": verif.get("binary_verified", False),
        "compile": verif.get("compile_verified", False),
        "provenance": verif.get("provenance_verified", False),
        "hashes": verif.get("hashes", {}),
        "issues": verif.get("issues", []),
    }
    if not verif["verified"]:
        result["status"] = verif.get("status", STATUS_CANDIDATE_INVALID)
        result["error"] = f"Candidate validation verification failed: {'; '.join(verif.get('issues', []))}"
        return result

    cand_meta = verif["metadata"]
    train_meta = verif["training_experiment"]
    if not plan_id:
        plan_id = cand_meta.get("plan_id") or train_meta.get("plan_id")
    result["plan_id"] = plan_id
    result["hypothesis_id"] = cand_meta.get("hypothesis_id") or train_meta.get("hypothesis_id")
    result["baseline_experiment"] = cand_meta.get("baseline_experiment") or train_meta.get("baseline_experiment")

    if verify_only:
        result["status"] = STATUS_READY
        return result

    # 3. Strict VALIDATION Partition Date Resolution & Non-Overlap Check
    val_plan = {"dataset": "validation"}
    dates_ok, dataset_type, val_from, val_to, dates_status = resolve_dataset_dates(
        val_plan,
        research_periods_path=research_periods_path,
        allow_unconfigured_dates=allow_unconfigured_dates,
    )
    if not dates_ok or dataset_type != "validation":
        result["status"] = dates_status if dates_status != "CONFIGURED" else STATUS_INVALID_DATASET
        result["error"] = f"Failed to resolve VALIDATION partition from {research_periods_path.name}."
        return result

    # Verify Training & Validation Non-Overlap
    train_from = train_meta.get("from") or train_meta.get("backtest_config", {}).get("from")
    train_to = train_meta.get("to") or train_meta.get("backtest_config", {}).get("to")

    t_from_d = parse_date(train_from)
    t_to_d = parse_date(train_to)
    v_from_d = parse_date(val_from)
    v_to_d = parse_date(val_to)

    if t_from_d and t_to_d and v_from_d and v_to_d:
        if (v_from_d <= t_to_d) and (v_to_d >= t_from_d):
            result["status"] = STATUS_DATASET_OVERLAP
            result["error"] = f"Validation period ({val_from} - {val_to}) overlaps training period ({train_from} - {train_to})."
            return result

    # Verify Validation does not match UNSEEN
    periods_cfg = load_research_periods(research_periods_path)
    unseen_p = periods_cfg.get("periods", {}).get("unseen", {})
    u_from = unseen_p.get("from")
    u_to = unseen_p.get("to")
    if u_from and u_to and parse_date(val_from) == parse_date(u_from) and parse_date(val_to) == parse_date(u_to):
        result["status"] = STATUS_INVALID_DATASET
        result["error"] = "Validation evaluation cannot use UNSEEN dataset partition."
        return result

    # Load system configuration for backtest
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        result["status"] = STATUS_CANDIDATE_INVALID
        result["error"] = f"Failed to load config.json: {str(e)}"
        return result

    mt5_data = Path(config.get("mt5_data", ""))
    terminal = Path(config.get("mt5_terminal", ""))
    sym = train_meta.get("symbol") or config.get("backtest", {}).get("symbol", "GBPUSD")
    tf = train_meta.get("timeframe") or config.get("backtest", {}).get("timeframe", "M15")
    mdl = config.get("backtest", {}).get("model", 1)

    result["backtest"]["configuration"] = {
        "dataset": "validation",
        "symbol": sym,
        "timeframe": tf,
        "model": mdl,
        "from": val_from,
        "to": val_to,
    }

    if dry_run:
        result["status"] = STATUS_READY
        result["backtest"]["status"] = "dry_run"
        result["backtest"]["expected_binary"] = verif["binary_path"]
        result["backtest"]["expected_report"] = f"{candidate_id}_report.htm"
        return result

    # Check port 3000 conflict
    if not mt5_launcher and not check_port_conflict():
        result["status"] = STATUS_TESTER_PORT_CONFLICT
        result["error"] = "Local port 3000 is occupied; MT5 tester core cannot bind."
        return result

    # Stage Candidate Binary
    sync_record = stage_candidate_binary(
        candidate_id=candidate_id,
        source_binary_path=Path(verif["binary_path"]),
        mt5_data_dir=mt5_data,
    )
    result["backtest"]["sync"] = sync_record
    if not sync_record.get("verified"):
        result["status"] = STATUS_BINARY_INVALID
        result["error"] = f"Candidate staging failed: {sync_record.get('error')}"
        return result

    # Generate tester INI config for candidate validation
    tester_config_path, report_name = generate_candidate_tester_config(
        candidate_id=candidate_id,
        expert_param=sync_record["expert_param"],
        config=config,
        from_date=val_from,
        to_date=val_to,
        symbol=sym,
        timeframe=tf,
        model=mdl,
    )
    mt5_report_path = mt5_data / report_name

    # Clear stale report/asset
    if mt5_report_path.exists():
        try:
            mt5_report_path.unlink()
        except Exception:
            pass
    stem = mt5_report_path.stem
    for asset in mt5_data.glob(f"{stem}*.png"):
        try:
            asset.unlink()
        except Exception:
            pass

    # Execute MT5 Strategy Tester
    start_time = datetime.now().astimezone().isoformat()
    cmd = [str(terminal), f"/config:{tester_config_path}"]

    if mt5_launcher:
        launch_res = mt5_launcher(cmd, timeout_seconds)
        proc_exit = launch_res.get("exit_code", 0)
        proc_timeout = launch_res.get("timeout", False)
    else:
        try:
            proc = subprocess.Popen(cmd)
            t0 = time.time()
            proc_timeout = False
            while proc.poll() is None:
                if time.time() - t0 > timeout_seconds:
                    proc.kill()
                    proc_timeout = True
                    break
                time.sleep(1)
            proc_exit = proc.returncode if not proc_timeout else -1
        except Exception as e:
            result["status"] = STATUS_MT5_LAUNCH_FAILED
            result["error"] = f"Failed to start MT5 process: {str(e)}"
            return result

    end_time = datetime.now().astimezone().isoformat()
    result["backtest"]["execution"] = {
        "start_time": start_time,
        "end_time": end_time,
        "exit_code": proc_exit,
        "timeout": proc_timeout,
    }

    if proc_timeout:
        result["status"] = STATUS_TESTER_TIMEOUT
        result["error"] = f"MT5 Strategy Tester timed out after {timeout_seconds} seconds."
        return result

    if proc_exit != 0 and proc_exit is not None:
        result["status"] = STATUS_TESTER_FAILED
        result["error"] = f"MT5 Strategy Tester exited with non-zero code {proc_exit}."
        return result

    # Verify Report
    is_rep_valid, rep_status, rep_info = verify_candidate_report(
        mt5_report_path,
        expected_candidate_id=candidate_id,
        expected_symbol=sym,
        expected_timeframe=tf,
    )
    result["backtest"]["report_info"] = rep_info
    if not is_rep_valid:
        result["status"] = rep_status
        result["error"] = f"Report verification failed: {rep_status}"
        return result

    # Copy assets to project tester/reports
    project_reports_dir = PROJECT_ROOT / "tester" / "reports"
    project_reports_dir.mkdir(parents=True, exist_ok=True)
    project_rep = project_reports_dir / report_name
    shutil.copy2(mt5_report_path, project_rep)

    for asset in mt5_data.glob(f"{stem}*.png"):
        shutil.copy2(asset, project_reports_dir / asset.name)

    # Parse Report
    try:
        parsed_result = parse_report(project_rep)
    except Exception as e:
        result["status"] = STATUS_PARSER_FAILED
        result["error"] = f"Failed to parse MT5 report metrics: {str(e)}"
        return result

    # Create Validation Experiment Archive (EXP-XXXX)
    try:
        exp_id = get_next_experiment_id(experiments_dir)
        exp_dir = experiments_dir / exp_id
        charts_dir = exp_dir / "charts"

        exp_dir.mkdir(parents=True, exist_ok=False)
        charts_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(project_rep, exp_dir / "report.htm")

        chart_files = []
        for asset in project_reports_dir.glob(f"{stem}*.png"):
            dest_asset = charts_dir / asset.name
            shutil.copy2(asset, dest_asset)
            chart_files.append(f"charts/{asset.name}")

        (exp_dir / "metrics.json").write_text(
            json.dumps(parsed_result, indent=2), encoding="utf-8"
        )

        backtest_cfg = {
            "symbol": sym,
            "timeframe": tf,
            "model": mdl,
            "from": val_from,
            "to": val_to,
            "deposit": config.get("backtest", {}).get("deposit", 10000),
            "currency": config.get("backtest", {}).get("currency", "USD"),
            "leverage": config.get("backtest", {}).get("leverage", "1:100"),
            "inputs": parsed_result["settings"]["inputs"],
        }
        rel_config_hash = calculate_configuration_fingerprint(backtest_cfg)
        rp_config_hash = calculate_research_periods_fingerprint(config_path=research_periods_path)
        env_meta = capture_environment_metadata(PROJECT_ROOT)

        repro_record = create_reproducibility_record(
            experiment_id=exp_id,
            candidate_id=candidate_id,
            hypothesis_id=cand_meta.get("hypothesis_id"),
            plan_id=plan_id,
            evaluation_type="validation",
            dataset_partition="validation",
            dataset_from=val_from,
            dataset_to=val_to,
            symbol=sym,
            timeframe=tf,
            model=mdl,
            deposit=config.get("backtest", {}).get("deposit", 10000),
            currency=config.get("backtest", {}).get("currency", "USD"),
            leverage=config.get("backtest", {}).get("leverage", "1:100"),
            candidate_source_sha256=verif["hashes"].get("source_after_sha256"),
            candidate_binary_sha256=verif["hashes"].get("source_after_ex5_sha256"),
            relevant_configuration_hash=rel_config_hash,
            research_periods_configuration_hash=rp_config_hash,
            training_experiment_id=training_experiment_id,
            environment_metadata=env_meta,
        )

        exp_metadata = {
            "experiment_id": exp_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "note": note or "Validation evaluation experiment",
            "candidate_id": candidate_id,
            "training_experiment_id": training_experiment_id,
            "plan_id": plan_id,
            "hypothesis_id": cand_meta.get("hypothesis_id"),
            "baseline_experiment": cand_meta.get("baseline_experiment"),
            "ea": cand_meta.get("ea"),
            "symbol": sym,
            "timeframe": tf,
            "from": val_from,
            "to": val_to,
            "dataset": {
                "partition": "validation",
                "from": val_from,
                "to": val_to,
                "source": "config/research_periods.json",
            },
            "evaluation_type": "validation",
            "report": "report.htm",
            "metrics": "metrics.json",
            "charts": chart_files,
            "candidate_source_sha256": verif["hashes"].get("source_after_sha256"),
            "candidate_ex5_sha256": verif["hashes"].get("source_after_ex5_sha256"),
            "relevant_configuration_hash": rel_config_hash,
            "research_periods_configuration_hash": rp_config_hash,
            "experiment_identity_fingerprint": repro_record["experiment_identity_fingerprint"],
            "reproducibility": repro_record,
            "backtest_config": backtest_cfg,
            "inputs": parsed_result["settings"]["inputs"],
            "tester_sync": sync_record,
            "git_commit": get_git_commit(PROJECT_ROOT),
            "status": "COMPLETED",
        }

        (exp_dir / "metadata.json").write_text(
            json.dumps(exp_metadata, indent=2), encoding="utf-8"
        )
        (exp_dir / "reproducibility.json").write_text(
            json.dumps(repro_record, indent=2), encoding="utf-8"
        )

        result["experiment"]["created"] = True
        result["experiment"]["experiment_id"] = exp_id
        result["experiment"]["directory"] = str(exp_dir)
        result["status"] = STATUS_SUCCESS

        # Rebuild manifest catalog
        from scripts.build_manifest import build_manifest
        build_manifest(experiments_dir=experiments_dir)

    except Exception as e:
        result["status"] = STATUS_EXPERIMENT_CREATION_FAILED
        result["error"] = f"Failed to create validation experiment directory or metadata: {str(e)}"
        return result

    finally:
        cleanup_staged_candidate(sync_record)

    return result


def execute_repeat_backtest(
    baseline_experiment_id: str,
    candidate_id: Optional[str] = None,
    dry_run: bool = False,
    verify_only: bool = False,
    timeout_seconds: int = 180,
    allow_unconfigured_dates: bool = False,
    note: Optional[str] = None,
    candidates_dir: Path = CANDIDATES_DIR,
    plans_dir: Path = PLANS_DIR,
    experiments_dir: Path = EXPERIMENTS_DIR,
    config_path: Path = CONFIG_PATH,
    research_periods_path: Path = RESEARCH_PERIODS_PATH,
    mt5_launcher=None,
) -> Dict[str, Any]:
    """
    Executes a controlled repeat-run of an existing experiment (EXP-XXXX).
    Enforces Phase 15 repeat execution isolation and pre-flight identity verification:
    1. Pre-flight verification: Candidate source and binary SHA-256 match recorded hashes.
    2. Dataset partition, dates, symbol, timeframe, model, backtest settings match.
    3. Research periods configuration fingerprint matches.
    4. Creates a NEW, isolated experiment archive (EXP-YYYY).
    5. Sets repeat_of_experiment_id = baseline_experiment_id and evaluation_type = "repeat".
    6. Verifies baseline experiment artifacts were NOT modified.
    """
    candidates_dir = Path(candidates_dir)
    plans_dir = Path(plans_dir)
    experiments_dir = Path(experiments_dir)
    config_path = Path(config_path)

    base_dir = experiments_dir / baseline_experiment_id
    base_meta_path = base_dir / "metadata.json"
    if not base_dir.is_dir() or not base_meta_path.is_file():
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": candidate_id,
            "status": EXPERIMENT_NOT_FOUND,
            "error": f"Baseline experiment '{baseline_experiment_id}' does not exist or lacks metadata.json.",
        }

    try:
        base_meta = json.loads(base_meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": candidate_id,
            "status": EXPERIMENT_NOT_FOUND,
            "error": f"Baseline experiment metadata unparseable: {str(e)}",
        }

    cand_id = candidate_id or base_meta.get("candidate_id")
    if not cand_id:
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": None,
            "status": CANDIDATE_NOT_FOUND,
            "error": f"Could not resolve candidate_id for repeat of baseline experiment '{baseline_experiment_id}'.",
        }

    # Verify Repeat Execution Prerequisites
    prereq_ok, prereq_status, prereq_issues, _ = verify_repeat_execution_prerequisites(
        baseline_exp_id=baseline_experiment_id,
        candidate_id=cand_id,
        experiments_dir=experiments_dir,
        candidates_dir=candidates_dir,
        plans_dir=plans_dir,
        research_periods_path=research_periods_path,
    )

    if not prereq_ok:
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": cand_id,
            "status": prereq_status,
            "error": f"Repeat execution pre-flight verification failed: {'; '.join(prereq_issues)}",
            "issues": prereq_issues,
        }

    if verify_only:
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": cand_id,
            "status": REPRODUCIBLE_IDENTITY,
            "verified": True,
            "verify_only": True,
        }

    sym = base_meta.get("symbol") or base_meta.get("backtest_config", {}).get("symbol", "GBPUSD")
    tf = base_meta.get("timeframe") or base_meta.get("backtest_config", {}).get("timeframe", "M15")
    from_date = base_meta.get("from") or base_meta.get("dataset", {}).get("from")
    to_date = base_meta.get("to") or base_meta.get("dataset", {}).get("to")
    dataset_type = base_meta.get("dataset", {}).get("partition") or base_meta.get("evaluation_type") or "training"
    plan_id = base_meta.get("plan_id")
    hyp_id = base_meta.get("hypothesis_id")

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        return {
            "candidate_id": cand_id,
            "status": STATUS_CANDIDATE_INVALID,
            "error": f"Failed to load config.json: {str(e)}",
        }

    mdl = base_meta.get("backtest_config", {}).get("model", config.get("backtest", {}).get("model", 1))

    if dry_run:
        return {
            "baseline_experiment": baseline_experiment_id,
            "candidate_id": cand_id,
            "status": REPRODUCIBLE_IDENTITY,
            "dry_run": True,
            "backtest": {
                "dataset": dataset_type,
                "symbol": sym,
                "timeframe": tf,
                "model": mdl,
                "from": from_date,
                "to": to_date,
            },
        }

    if not mt5_launcher and not check_port_conflict():
        return {
            "candidate_id": cand_id,
            "status": STATUS_TESTER_PORT_CONFLICT,
            "error": "Local port 3000 is occupied; MT5 tester core cannot bind.",
        }

    verif = verify_candidate(cand_id, candidates_dir=candidates_dir, plans_dir=plans_dir, experiments_dir=experiments_dir)
    if not verif["verified"]:
        return {
            "candidate_id": cand_id,
            "status": verif["status"],
            "error": f"Candidate verification failed: {'; '.join(verif['issues'])}",
        }

    mt5_data = Path(config.get("mt5_data", ""))
    sync_record = stage_candidate_binary(
        candidate_id=cand_id,
        source_binary_path=Path(verif["binary_path"]),
        mt5_data_dir=mt5_data,
    )
    if not sync_record.get("verified"):
        return {
            "candidate_id": cand_id,
            "status": STATUS_BINARY_INVALID,
            "error": f"Candidate staging failed: {sync_record.get('error')}",
        }

    try:
        mt5_data = Path(config.get("mt5_data", ""))
        terminal = Path(config.get("mt5_terminal", ""))

        tester_config_path, report_name = generate_candidate_tester_config(
            candidate_id=cand_id,
            expert_param=sync_record["expert_param"],
            config=config,
            from_date=from_date,
            to_date=to_date,
            symbol=sym,
            timeframe=tf,
            model=mdl,
        )
        mt5_report_path = mt5_data / report_name

        if mt5_report_path.exists():
            try:
                mt5_report_path.unlink()
            except Exception:
                pass

        cmd = [str(terminal), f"/config:{tester_config_path}"]

        if mt5_launcher:
            launch_res = mt5_launcher(cmd, timeout_seconds)
            proc_exit = launch_res.get("exit_code", 0)
            proc_timeout = launch_res.get("timeout", False)
        else:
            proc = subprocess.Popen(cmd)
            t0 = time.time()
            proc_timeout = False
            while proc.poll() is None:
                if time.time() - t0 > timeout_seconds:
                    proc.kill()
                    proc_timeout = True
                    break
                time.sleep(1)
            proc_exit = proc.returncode if not proc_timeout else -1

        if proc_timeout or (proc_exit != 0 and proc_exit is not None):
            return {
                "candidate_id": cand_id,
                "status": STATUS_TESTER_TIMEOUT if proc_timeout else STATUS_TESTER_FAILED,
                "error": "Tester failed or timed out.",
            }

        is_rep_valid, rep_status, rep_info = verify_candidate_report(
            mt5_report_path,
            expected_candidate_id=cand_id,
            expected_symbol=sym,
            expected_timeframe=tf,
        )
        if not is_rep_valid:
            return {"candidate_id": cand_id, "status": rep_status, "error": f"Report verification failed: {rep_status}"}

        project_reports_dir = PROJECT_ROOT / "tester" / "reports"
        project_reports_dir.mkdir(parents=True, exist_ok=True)
        project_rep = project_reports_dir / report_name
        shutil.copy2(mt5_report_path, project_rep)

        parsed_result = parse_report(project_rep)

        # Create NEW immutable repeat experiment archive
        exp_id = get_next_experiment_id(experiments_dir)
        exp_dir = experiments_dir / exp_id
        charts_dir = exp_dir / "charts"

        exp_dir.mkdir(parents=True, exist_ok=False)
        charts_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(project_rep, exp_dir / "report.htm")

        chart_files = []
        stem = mt5_report_path.stem
        for asset in project_reports_dir.glob(f"{stem}*.png"):
            dest_asset = charts_dir / asset.name
            shutil.copy2(asset, dest_asset)
            chart_files.append(f"charts/{asset.name}")

        (exp_dir / "metrics.json").write_text(json.dumps(parsed_result, indent=2), encoding="utf-8")

        backtest_cfg = {
            "symbol": sym,
            "timeframe": tf,
            "model": mdl,
            "from": from_date,
            "to": to_date,
            "deposit": config.get("backtest", {}).get("deposit", 10000),
            "currency": config.get("backtest", {}).get("currency", "USD"),
            "leverage": config.get("backtest", {}).get("leverage", "1:100"),
            "inputs": parsed_result["settings"]["inputs"],
        }
        rel_config_hash = calculate_configuration_fingerprint(backtest_cfg)
        rp_config_hash = calculate_research_periods_fingerprint(config_path=research_periods_path)
        env_meta = capture_environment_metadata(PROJECT_ROOT)

        repro_record = create_reproducibility_record(
            experiment_id=exp_id,
            candidate_id=cand_id,
            hypothesis_id=hyp_id,
            plan_id=plan_id,
            evaluation_type="repeat",
            dataset_partition=dataset_type,
            dataset_from=from_date,
            dataset_to=to_date,
            symbol=sym,
            timeframe=tf,
            model=mdl,
            deposit=config.get("backtest", {}).get("deposit", 10000),
            currency=config.get("backtest", {}).get("currency", "USD"),
            leverage=config.get("backtest", {}).get("leverage", "1:100"),
            candidate_source_sha256=verif["hashes"].get("source_after_sha256"),
            candidate_binary_sha256=verif["hashes"].get("source_after_ex5_sha256"),
            relevant_configuration_hash=rel_config_hash,
            research_periods_configuration_hash=rp_config_hash,
            repeat_of_experiment_id=baseline_experiment_id,
            environment_metadata=env_meta,
        )

        exp_metadata = {
            "experiment_id": exp_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "note": note or f"Repeat execution of baseline experiment {baseline_experiment_id}",
            "candidate_id": cand_id,
            "repeat_of_experiment_id": baseline_experiment_id,
            "plan_id": plan_id,
            "hypothesis_id": hyp_id,
            "baseline_experiment": base_meta.get("baseline_experiment"),
            "ea": base_meta.get("ea"),
            "symbol": sym,
            "timeframe": tf,
            "from": from_date,
            "to": to_date,
            "dataset": {
                "partition": dataset_type,
                "from": from_date,
                "to": to_date,
                "source": "config/research_periods.json",
            },
            "evaluation_type": "repeat",
            "report": "report.htm",
            "metrics": "metrics.json",
            "charts": chart_files,
            "candidate_source_sha256": verif["hashes"].get("source_after_sha256"),
            "candidate_ex5_sha256": verif["hashes"].get("source_after_ex5_sha256"),
            "relevant_configuration_hash": rel_config_hash,
            "research_periods_configuration_hash": rp_config_hash,
            "experiment_identity_fingerprint": repro_record["experiment_identity_fingerprint"],
            "reproducibility": repro_record,
            "backtest_config": backtest_cfg,
            "inputs": parsed_result["settings"]["inputs"],
            "tester_sync": sync_record,
            "git_commit": get_git_commit(PROJECT_ROOT),
            "status": "COMPLETED",
        }

        (exp_dir / "metadata.json").write_text(json.dumps(exp_metadata, indent=2), encoding="utf-8")
        (exp_dir / "reproducibility.json").write_text(json.dumps(repro_record, indent=2), encoding="utf-8")

        from scripts.build_manifest import build_manifest
        build_manifest(experiments_dir=experiments_dir)

        return {
            "candidate_id": cand_id,
            "baseline_experiment": baseline_experiment_id,
            "status": STATUS_SUCCESS,
            "experiment": {
                "created": True,
                "experiment_id": exp_id,
                "directory": str(exp_dir),
                "repeat_of_experiment_id": baseline_experiment_id,
            },
            "reproducibility": repro_record,
        }

    finally:
        cleanup_staged_candidate(sync_record)


def main():
    parser = argparse.ArgumentParser(
        description="AI-EA-Lab Phase 9: Run controlled MT5 backtest for a verified candidate."
    )
    parser.add_argument(
        "--candidate",
        type=str,
        default=None,
        help="Candidate identifier (e.g. CAND-0001).",
    )
    parser.add_argument(
        "--repeat",
        type=str,
        default=None,
        help="Baseline experiment ID to repeat under identical conditions (e.g. EXP-0001).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution and preview backtest parameters without running MT5.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Perform candidate verification, hash check, and provenance check without MT5 execution.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON format.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Strategy Tester execution timeout in seconds (default: 180).",
    )
    parser.add_argument(
        "--note",
        type=str,
        default=None,
        help="Optional note to record in experiment metadata.",
    )
    parser.add_argument(
        "--allow-unconfigured-dates",
        action="store_true",
        help="Allow testing with fallback dates if research_periods.json is unconfigured.",
    )
    parser.add_argument(
        "--validation",
        type=str,
        default=None,
        help="Execute out-of-sample validation against specified training experiment ID (e.g. EXP-0008).",
    )
    parser.add_argument(
        "--plan",
        type=str,
        default=None,
        help="Optional experiment plan ID to associate with validation run.",
    )

    args = parser.parse_args()

    if args.validation:
        if not args.candidate:
            parser.error("--candidate must be specified when using --validation.")
        result = execute_candidate_validation(
            candidate_id=args.candidate,
            training_experiment_id=args.validation,
            plan_id=args.plan,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
            timeout_seconds=args.timeout,
            allow_unconfigured_dates=args.allow_unconfigured_dates,
            note=args.note,
        )
    elif args.repeat:
        result = execute_repeat_backtest(
            baseline_experiment_id=args.repeat,
            candidate_id=args.candidate,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
            timeout_seconds=args.timeout,
            allow_unconfigured_dates=args.allow_unconfigured_dates,
            note=args.note,
        )
    elif args.candidate:
        result = execute_candidate_backtest(
            candidate_id=args.candidate,
            dry_run=args.dry_run,
            verify_only=args.verify_only,
            timeout_seconds=args.timeout,
            allow_unconfigured_dates=args.allow_unconfigured_dates,
            note=args.note,
        )
    else:
        parser.error("Either --candidate or --repeat must be specified.")

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_human_readable_output(result))


if __name__ == "__main__":
    main()
