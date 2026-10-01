"""
Research Context Builder

Assembles a standardized research context object dynamically from project files:
- Project state (config.json)
- Historical experiment catalog & metrics (experiments/manifest.json, experiments/EXP-XXXX/)
- Research period partitions (config/research_periods.json)
- Operational safety constraints

Does NOT duplicate experiment archives manually or fabricate data.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = PROJECT_ROOT / "config.json"
MANIFEST_PATH = PROJECT_ROOT / "experiments" / "manifest.json"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"
DEFAULT_CONTEXT_PATH = PROJECT_ROOT / "research" / "context" / "latest_context.json"

from scripts.research_periods import is_periods_configured, load_research_periods


def load_project_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_manifest(manifest_path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(manifest_path) if manifest_path else MANIFEST_PATH
    if not path.exists():
        return {"schema_version": 1, "total_experiments": 0, "experiments": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"schema_version": 1, "total_experiments": 0, "experiments": []}


def get_historical_experiment_details(
    exp_id: str,
    experiments_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """
    Safely retrieves full metadata and structured metrics for a specific experiment ID.
    Returns None if experiment does not exist.
    """
    base_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR
    exp_dir = base_dir / exp_id
    if not exp_dir.is_dir():
        return None

    metadata_path = exp_dir / "metadata.json"
    metrics_path = exp_dir / "metrics.json"

    meta = {}
    if metadata_path.is_file():
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metrics_root = {}
    if metrics_path.is_file():
        try:
            metrics_root = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    settings = metrics_root.get("settings", {})
    metrics = metrics_root.get("metrics", {})
    validation = metrics_root.get("validation", {})

    inputs = meta.get("inputs") or settings.get("inputs") or {}

    return {
        "id": exp_id,
        "created_at": meta.get("created_at"),
        "note": meta.get("note"),
        "ea": meta.get("ea") or settings.get("expert"),
        "symbol": meta.get("symbol") or settings.get("symbol"),
        "timeframe": meta.get("timeframe") or settings.get("timeframe"),
        "from": meta.get("from") or settings.get("from"),
        "to": meta.get("to") or settings.get("to"),
        "inputs": inputs,
        "performance": {
            "total_net_profit": metrics.get("total_net_profit"),
            "gross_profit": metrics.get("gross_profit"),
            "gross_loss": metrics.get("gross_loss"),
            "profit_factor": metrics.get("profit_factor"),
            "expected_payoff": metrics.get("expected_payoff"),
            "recovery_factor": metrics.get("recovery_factor"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
        },
        "risk": {
            "balance_drawdown_absolute": metrics.get("balance_drawdown_absolute"),
            "equity_drawdown_absolute": metrics.get("equity_drawdown_absolute"),
            "balance_drawdown_maximal": metrics.get("balance_drawdown_maximal"),
            "equity_drawdown_maximal": metrics.get("equity_drawdown_maximal"),
        },
        "trading": {
            "total_trades": metrics.get("total_trades"),
            "total_deals": metrics.get("total_deals"),
            "profit_trades": metrics.get("profit_trades"),
            "loss_trades": metrics.get("loss_trades"),
            "average_profit_trade": metrics.get("average_profit_trade"),
            "average_loss_trade": metrics.get("average_loss_trade"),
        },
        "data_quality": {
            "history_quality_percent": metrics.get("history_quality_percent"),
            "bars": metrics.get("bars"),
            "ticks": metrics.get("ticks"),
        },
        "validation_passed": validation.get("test_executed", False),
    }


def normalize_inputs(inputs: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """
    Normalizes inputs to string representations for strict key-value comparison.
    """
    if not isinstance(inputs, dict):
        return {}
    return {str(k): str(v) for k, v in sorted(inputs.items())}


def check_duplicate_configuration(
    proposed_inputs: Dict[str, Any],
    ea: str,
    symbol: str,
    timeframe: str,
    context: Dict[str, Any],
) -> Optional[str]:
    """
    Checks if an identical parameter set for the same EA, symbol, and timeframe
    has already been tested in historical experiments.
    Returns the matching experiment ID if duplicate is found, else None.
    """
    norm_proposed = normalize_inputs(proposed_inputs)

    for entry in context.get("tested_parameter_configurations", []):
        if entry.get("ea") == ea and entry.get("symbol") == symbol and entry.get("timeframe") == timeframe:
            tested_norm = normalize_inputs(entry.get("inputs"))
            if norm_proposed == tested_norm:
                return entry.get("experiment_id")

    return None


def build_research_context(
    project_root: Optional[Path] = None,
    experiments_dir: Optional[Path] = None,
    manifest_path: Optional[Path] = None,
    periods_path: Optional[Path] = None,
    config_path: Optional[Path] = None,
    research_periods_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Compiles the unified research context.
    """
    root = Path(project_root) if project_root else PROJECT_ROOT
    c_path = Path(config_path) if config_path else (root / "config.json")
    cfg = load_project_config(c_path)
    manifest = load_manifest(manifest_path)
    p_path = periods_path or research_periods_path
    periods_cfg = load_research_periods(p_path)

    # Project state
    ea_config = cfg.get("ea", {})
    backtest_config = cfg.get("backtest", {})
    ea_name = ea_config.get("name", "UnknownEA")
    symbol = backtest_config.get("symbol")
    timeframe = backtest_config.get("timeframe")

    raw_manifest_exps = manifest.get("experiments", [])
    total_experiments = len(raw_manifest_exps)
    latest_exp_id = raw_manifest_exps[-1]["id"] if raw_manifest_exps else None

    # Load rich historical experiment records
    historical_experiments: List[Dict[str, Any]] = []
    tested_configurations: List[Dict[str, Any]] = []

    for entry in raw_manifest_exps:
        exp_id = entry.get("id")
        details = get_historical_experiment_details(exp_id, experiments_dir=experiments_dir)
        if details:
            details["dataset"] = entry.get("dataset")
            details["dataset_status"] = entry.get("dataset_status", "unconfigured")
            historical_experiments.append(details)
            tested_configurations.append({
                "experiment_id": exp_id,
                "ea": details.get("ea"),
                "symbol": details.get("symbol"),
                "timeframe": details.get("timeframe"),
                "inputs": details.get("inputs", {}),
            })
        else:
            # Fallback to lightweight manifest data if directory details unreadable
            historical_experiments.append(entry)

    periods_configured = is_periods_configured(periods_cfg)
    periods_status = "configured" if periods_configured else "unconfigured"

    context = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "project_state": {
            "ea_name": ea_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "total_experiments": total_experiments,
            "latest_experiment_id": latest_exp_id,
            "backtest_defaults": backtest_config,
        },
        "historical_experiments": historical_experiments,
        "tested_parameter_configurations": tested_configurations,
        "research_periods": {
            "status": periods_status,
            "is_configured": periods_configured,
            "periods": periods_cfg.get("periods", {}),
            "note": periods_cfg.get("note", ""),
        },
        "constraints": {
            "no_live_trading": True,
            "no_broker_execution": True,
            "no_automatic_deployment": True,
            "no_unsupported_assumptions": True,
            "no_fabricated_data": True,
            "human_approval_required": True,
            "max_primary_variables_per_experiment": 1,
        },
    }

    try:
        from scripts.memory import build_research_memory_context
        context["research_memory"] = build_research_memory_context()
    except Exception:
        context["research_memory"] = {}

    return context



def save_research_context(
    context: Dict[str, Any],
    output_path: Optional[Path] = None,
) -> Path:
    out = Path(output_path) if output_path else DEFAULT_CONTEXT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(context, indent=2), encoding="utf-8")
    return out
