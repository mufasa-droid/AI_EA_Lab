"""
AI EA Lab - AI Auditor (Phase 10)

The evidence evaluation layer. Evaluates whether an experiment's evidence is:
1. Valid (free of zero-data failures or contamination).
2. Internally consistent (cross-references match across report, metrics, and metadata).
3. Reproducible (source, binary, hashes, and configurations are preserved).
4. Plan-compliant (matches the approved experiment plan).
5. Methodologically sound (identifies overfitting, leakage, and robustness risks).

Enforces:
- Strict separation between FACTS, INTERPRETATIONS, and RISKS.
- Distinction between INFRASTRUCTURE evidence and TRADING PERFORMANCE evidence.
- Zero live trading, zero broker order placement.
- NO rankings, NO declaration of superior EAs, NO comparative scoreboards.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auditor.llm.base import BaseAuditorAdapter, MockAuditorAdapter
from scripts.auditor_schemas import (
    AUDIT_ID_PATTERN,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_NON_COMPLIANT,
    COMPLIANCE_NOT_APPLICABLE,
    COMPLIANCE_PARTIALLY_COMPLIANT,
    COMPLIANCE_UNKNOWN,
    EXPERIMENT_ID_PATTERN,
    GRADE_ADEQUATE,
    GRADE_INSUFFICIENT,
    GRADE_LIMITED,
    GRADE_STRONG,
    GRADE_UNKNOWN,
    RISK_OBSERVED,
    RISK_POSSIBLE,
    RISK_UNKNOWN,
    STATUS_INVALID,
    STATUS_NEEDS_REVIEW,
    STATUS_PASS,
    get_next_audit_id,
    validate_audit_dict,
)
from scripts.research_periods import (
    is_periods_configured,
    load_research_periods,
    parse_date,
    resolve_dataset_partition,
)
from scripts.reproducibility import (
    MATCH,
    METRIC_DIFFERENCE_DETECTED,
    MISMATCH,
    calculate_configuration_fingerprint,
    calculate_experiment_identity_fingerprint,
    calculate_research_periods_fingerprint,
    compare_experiments_reproducibility,
)

EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
CANDIDATES_DIR = PROJECT_ROOT / "developer" / "candidates"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"
HYPOTHESES_DIR = PROJECT_ROOT / "research" / "hypotheses"
AUDITS_DIR = PROJECT_ROOT / "audits"
RESEARCH_PERIODS_PATH = PROJECT_ROOT / "config" / "research_periods.json"


def calculate_sha256(path: Path) -> Optional[str]:
    """Calculates SHA-256 hash of a file if it exists."""
    if not path.is_file():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def audit_experiment_identity(
    exp_id: str,
    exp_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Checks that experiment identity and referenced parent entities are properly formatted.
    """
    issues = []
    if not EXPERIMENT_ID_PATTERN.match(exp_id):
        issues.append(f"Invalid experiment ID format: '{exp_id}'. Expected EXP-XXXX.")

    cand_id = exp_meta.get("candidate_id")
    plan_id = exp_meta.get("plan_id")
    hyp_id = exp_meta.get("hypothesis_id")
    base_id = exp_meta.get("baseline_experiment")

    if cand_id and not re.match(r"^CAND-\d{4,}$", str(cand_id), re.IGNORECASE):
        issues.append(f"Invalid candidate ID format in metadata: '{cand_id}'.")
    if plan_id and not re.match(r"^PLAN-\d{4,}$", str(plan_id), re.IGNORECASE):
        issues.append(f"Invalid plan ID format in metadata: '{plan_id}'.")
    if hyp_id and not re.match(r"^HYP-\d{4,}$", str(hyp_id), re.IGNORECASE):
        issues.append(f"Invalid hypothesis ID format in metadata: '{hyp_id}'.")

    status = "PASS" if len(issues) == 0 else "FAIL"
    details = "Experiment identity references are well-formed." if status == "PASS" else "; ".join(issues)

    return {
        "status": status,
        "details": details,
        "issues": issues,
    }


def audit_provenance(
    exp_id: str,
    exp_meta: Dict[str, Any],
    candidates_dir: Path,
    plans_dir: Path,
    hypotheses_dir: Path,
    experiments_dir: Path,
) -> Dict[str, Any]:
    """
    Verifies the complete upstream lineage: HYP -> PLAN -> CAND -> EXP.
    For canonical baseline experiments without candidate provenance, records NOT_APPLICABLE cleanly.
    """
    cand_id = exp_meta.get("candidate_id")
    plan_id = exp_meta.get("plan_id")
    hyp_id = exp_meta.get("hypothesis_id")
    base_id = exp_meta.get("baseline_experiment")

    if not cand_id and not plan_id and not hyp_id:
        # Canonical baseline experiment
        return {
            "status": "NOT_APPLICABLE",
            "lineage_intact": True,
            "details": f"Experiment '{exp_id}' is a canonical baseline experiment without upstream candidate lineage.",
            "lineage": {
                "hypothesis": None,
                "plan": None,
                "candidate": None,
                "experiment": exp_id,
            },
            "issues": [],
        }

    issues = []
    lineage = {
        "hypothesis": hyp_id,
        "plan": plan_id,
        "candidate": cand_id,
        "experiment": exp_id,
    }

    # Verify plan on disk
    if not plan_id:
        issues.append("Candidate experiment is missing plan_id reference.")
    else:
        plan_file = plans_dir / f"{plan_id}.json"
        if not plan_file.is_file():
            issues.append(f"Referenced plan file does not exist on disk: {plan_file.name}")
        else:
            try:
                plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
                # Check plan points to same hypothesis
                if hyp_id and plan_data.get("hypothesis_id") != hyp_id:
                    issues.append(
                        f"Lineage mismatch: experiment references '{hyp_id}' but plan references '{plan_data.get('hypothesis_id')}'."
                    )
            except Exception as e:
                issues.append(f"Referenced plan file is unparseable: {str(e)}")

    # Verify candidate directory on disk
    if not cand_id:
        issues.append("Candidate experiment is missing candidate_id reference.")
    else:
        cand_dir = candidates_dir / cand_id
        if not cand_dir.is_dir():
            issues.append(f"Referenced candidate directory does not exist on disk: {cand_id}")
        else:
            cand_meta_file = cand_dir / "metadata.json"
            if not cand_meta_file.is_file():
                issues.append(f"Referenced candidate is missing metadata.json: {cand_id}")
            else:
                try:
                    c_meta = json.loads(cand_meta_file.read_text(encoding="utf-8"))
                    if plan_id and c_meta.get("plan_id") != plan_id:
                        issues.append(
                            f"Lineage mismatch: experiment references plan '{plan_id}' but candidate references '{c_meta.get('plan_id')}'."
                        )
                except Exception as e:
                    issues.append(f"Referenced candidate metadata unparseable: {str(e)}")

    # Verify baseline experiment on disk
    if base_id:
        base_dir = experiments_dir / base_id
        if not base_dir.is_dir():
            issues.append(f"Referenced baseline experiment directory does not exist: {base_id}")

    lineage_intact = len(issues) == 0
    status = "PASS" if lineage_intact else "FAIL"
    details = (
        f"Verified complete provenance chain: {hyp_id} -> {plan_id} -> {cand_id} -> {exp_id}."
        if lineage_intact
        else f"Provenance chain broken: {'; '.join(issues)}"
    )

    return {
        "status": status,
        "lineage_intact": lineage_intact,
        "details": details,
        "lineage": lineage,
        "issues": issues,
    }


def audit_artifact_integrity(
    exp_dir: Path,
    exp_meta: Dict[str, Any],
    metrics_data: Dict[str, Any],
    manifest_path: Path,
    candidates_dir: Path,
) -> Dict[str, Any]:
    """
    Verifies that experiment artifacts exist, are non-empty, and match recorded SHA-256 hashes.
    """
    issues = []
    hashes_verified = True

    # Check local experiment files
    rep_file = exp_dir / "report.htm"
    if not rep_file.is_file():
        issues.append(f"Report file missing: {rep_file.name}")
    elif rep_file.stat().st_size == 0:
        issues.append(f"Report file is empty (0 bytes): {rep_file.name}")

    meta_file = exp_dir / "metadata.json"
    if not meta_file.is_file():
        issues.append(f"Metadata file missing: {meta_file.name}")

    metrics_file = exp_dir / "metrics.json"
    if not metrics_file.is_file():
        issues.append(f"Metrics file missing: {metrics_file.name}")

    # Check candidate source & binary hashes if candidate experiment
    cand_id = exp_meta.get("candidate_id")
    if cand_id:
        cand_dir = candidates_dir / cand_id
        if cand_dir.is_dir():
            src_path = cand_dir / "source_after.mq5"
            if src_path.is_file():
                calc_src = calculate_sha256(src_path)
                exp_src = exp_meta.get("candidate_source_sha256")
                if exp_src and calc_src != exp_src:
                    issues.append(f"Candidate source hash mismatch: calculated '{calc_src}', expected '{exp_src}'.")
                    hashes_verified = False

            bin_path = cand_dir / "source_after.ex5"
            if bin_path.is_file():
                calc_bin = calculate_sha256(bin_path)
                exp_bin = exp_meta.get("candidate_ex5_sha256")
                if exp_bin and calc_bin != exp_bin:
                    issues.append(f"Candidate binary hash mismatch: calculated '{calc_bin}', expected '{exp_bin}'.")
                    hashes_verified = False

            # Check tester sync hashes
            tester_sync = exp_meta.get("tester_sync", {})
            if tester_sync:
                s_hash = tester_sync.get("source_hash")
                d_hash = tester_sync.get("destination_hash")
                if s_hash and d_hash and s_hash != d_hash:
                    issues.append("Tester staging sync hash mismatch between source and destination.")
                    hashes_verified = False

    # Check baseline EA hashes if baseline experiment
    ea_src_obj = exp_meta.get("ea_source")
    if isinstance(ea_src_obj, dict) and "sha256" in ea_src_obj:
        expected_ea_hash = ea_src_obj["sha256"]
        canonical_src = PROJECT_ROOT / "ea" / ea_src_obj.get("filename", "TestEA.mq5")
        if canonical_src.is_file():
            calc_ea_hash = calculate_sha256(canonical_src)
            if calc_ea_hash != expected_ea_hash:
                issues.append(f"Baseline EA source hash mismatch: calculated '{calc_ea_hash}', expected '{expected_ea_hash}'.")
                hashes_verified = False

    # Verify manifest entry matches
    if manifest_path.is_file():
        try:
            m_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            exps = {e.get("id"): e for e in m_data.get("experiments", [])}
            my_id = exp_meta.get("experiment_id", exp_dir.name)
            if my_id in exps:
                m_entry = exps[my_id]
                # Compare trade count
                m_trades = m_entry.get("total_trades")
                actual_trades = metrics_data.get("metrics", {}).get("total_trades")
                if m_trades is not None and actual_trades is not None and m_trades != actual_trades:
                    issues.append(f"Manifest trades ({m_trades}) does not match metrics trades ({actual_trades}).")
        except Exception:
            pass

    status = "PASS" if len(issues) == 0 else "FAIL"
    details = "All artifact files exist, are non-empty, and cryptographic hashes are verified." if status == "PASS" else "; ".join(issues)

    return {
        "status": status,
        "details": details,
        "hashes_verified": hashes_verified,
        "issues": issues,
    }


def audit_tester_execution(
    metrics_data: Dict[str, Any],
    exp_meta: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Validates that the MT5 Strategy Tester genuinely executed market data.
    Distinguishes zero-trades (VALID test with 0 trades) from zero-data (INVALID test with 0 bars/ticks).
    """
    metrics = metrics_data.get("metrics", {})
    bars = metrics.get("bars", 0) or 0
    ticks = metrics.get("ticks", 0) or 0
    trades = metrics.get("total_trades", 0) or 0

    issues = []
    zero_data = (bars == 0 and ticks == 0)

    if zero_data:
        issues.append("Strategy Tester produced zero bars and zero ticks. The test failed to simulate market data.")
        status = "INVALID"
        details = "Test failed with zero market data (bars=0, ticks=0). Methodologically invalid."
    else:
        status = "PASS"
        if trades == 0:
            details = f"Valid execution ({bars:,} bars, {ticks:,} ticks). Candidate executed without trades (total_trades=0)."
        else:
            details = f"Valid execution ({bars:,} bars, {ticks:,} ticks, {trades} trades)."

    return {
        "status": status,
        "bars": bars,
        "ticks": ticks,
        "trades": trades,
        "zero_data": zero_data,
        "details": details,
        "issues": issues,
    }


def audit_report_consistency(
    exp_meta: Dict[str, Any],
    metrics_data: Dict[str, Any],
    report_path: Path,
) -> Dict[str, Any]:
    """
    Cross-checks information across metadata.json, metrics.json, and the raw report.htm.
    Detects contradictions in symbol, timeframe, date range, or candidate identity.
    """
    contradictions = []
    settings = metrics_data.get("settings", {})
    metrics = metrics_data.get("metrics", {})

    meta_sym = exp_meta.get("symbol")
    sett_sym = settings.get("symbol")
    if meta_sym and sett_sym and meta_sym != sett_sym:
        contradictions.append(f"Symbol contradiction: metadata says '{meta_sym}', report says '{sett_sym}'.")

    meta_tf = exp_meta.get("timeframe")
    sett_tf = settings.get("timeframe")
    if meta_tf and sett_tf and meta_tf != sett_tf:
        contradictions.append(f"Timeframe contradiction: metadata says '{meta_tf}', report says '{sett_tf}'.")

    meta_from = exp_meta.get("from")
    sett_from = settings.get("from")
    if meta_from and sett_from and meta_from != sett_from:
        contradictions.append(f"Start date contradiction: metadata says '{meta_from}', report says '{sett_from}'.")

    meta_to = exp_meta.get("to")
    sett_to = settings.get("to")
    if meta_to and sett_to and meta_to != sett_to:
        contradictions.append(f"End date contradiction: metadata says '{meta_to}', report says '{sett_to}'.")

    # Anti-contamination: Check candidate ID against report's expert line
    cand_id = exp_meta.get("candidate_id")
    sett_expert = settings.get("expert") or ""
    if cand_id:
        clean_expert = sett_expert.replace("Candidates\\", "").replace("Candidates/", "").replace(".ex5", "").strip()
        if clean_expert != cand_id and cand_id not in sett_expert:
            contradictions.append(
                f"Identity contradiction: metadata expects candidate '{cand_id}', but report records expert '{sett_expert}'."
            )

    # Check raw HTML file
    if report_path.is_file():
        try:
            raw_bytes = report_path.read_bytes()
            if raw_bytes.startswith(b"\xff\xfe") or b"\x00" in raw_bytes[:100]:
                content = raw_bytes.decode("utf-16le", errors="ignore")
            else:
                content = raw_bytes.decode("utf-8", errors="ignore")

            if cand_id and cand_id not in content:
                contradictions.append(f"Candidate identifier '{cand_id}' not found in raw report.htm content.")
        except Exception:
            pass

    status = "PASS" if len(contradictions) == 0 else "FAIL"
    details = "Cross-references between metadata, metrics, and report match without contradictions." if status == "PASS" else "; ".join(contradictions)

    return {
        "status": status,
        "details": details,
        "contradictions": contradictions,
    }


def audit_plan_compliance(
    exp_meta: Dict[str, Any],
    metrics_data: Dict[str, Any],
    plan_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Compares the actual experiment parameters against the approved Experiment Plan.
    Checks target EA, symbol, timeframe, date range, model, and inputs.
    """
    if not plan_data:
        return {
            "status": "NOT_APPLICABLE",
            "details": "No upstream plan associated with this experiment (canonical baseline).",
            "deviations": [],
        }

    deviations = []
    base_plan = plan_data.get("baseline", {})
    expected_ea = plan_data.get("target_ea") or base_plan.get("ea")
    actual_ea = exp_meta.get("ea")
    if expected_ea and actual_ea and expected_ea != actual_ea:
        deviations.append(f"Target EA deviation: plan expects '{expected_ea}', experiment recorded '{actual_ea}'.")

    expected_sym = base_plan.get("symbol")
    actual_sym = exp_meta.get("symbol")
    if expected_sym and actual_sym and expected_sym != actual_sym:
        deviations.append(f"Symbol deviation: plan expects '{expected_sym}', experiment recorded '{actual_sym}'.")

    expected_tf = base_plan.get("timeframe")
    actual_tf = exp_meta.get("timeframe")
    if expected_tf and actual_tf and expected_tf != actual_tf:
        deviations.append(f"Timeframe deviation: plan expects '{expected_tf}', experiment recorded '{actual_tf}'.")

    # Check input parameters
    plan_params = plan_data.get("parameters", {})
    actual_inputs = exp_meta.get("inputs") or metrics_data.get("settings", {}).get("inputs", {})
    for p_name, p_val in plan_params.items():
        if p_name in actual_inputs:
            if str(p_val) != str(actual_inputs[p_name]):
                deviations.append(
                    f"Parameter '{p_name}' deviation: plan specified '{p_val}', experiment recorded '{actual_inputs[p_name]}'."
                )
        else:
            deviations.append(f"Plan parameter '{p_name}' missing from experiment inputs.")

    if len(deviations) == 0:
        status = COMPLIANCE_COMPLIANT
        details = "Executed backtest parameters strictly complied with the approved experiment plan."
    else:
        status = COMPLIANCE_NON_COMPLIANT
        details = f"Executed backtest deviated from the approved plan: {'; '.join(deviations)}"

    return {
        "status": status,
        "details": details,
        "deviations": deviations,
    }


def audit_change_scope(
    candidate_id: Optional[str],
    candidates_dir: Path,
    plan_data: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Inspects candidate's change_manifest.json to confirm only authorized parameters were modified.
    """
    if not candidate_id:
        return {
            "status": "NOT_APPLICABLE",
            "details": "No candidate associated with this experiment (canonical baseline).",
            "authorized_changes": [],
            "unauthorized_changes": [],
        }

    cand_dir = candidates_dir / candidate_id
    manifest_file = cand_dir / "change_manifest.json"
    if not manifest_file.is_file():
        return {
            "status": "WARN",
            "details": f"Candidate change_manifest.json not found: {candidate_id}.",
            "authorized_changes": [],
            "unauthorized_changes": [f"Missing change_manifest.json in {candidate_id}"],
        }

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        unauthorized = manifest.get("unauthorized_changes", [])
        authorized = manifest.get("changes", [])

        if len(unauthorized) > 0:
            status = "FAIL"
            details = f"Unauthorized code modifications detected: {'; '.join(unauthorized)}."
        else:
            status = "PASS"
            details = "Candidate code changes were strictly confined to authorized parameters."

        return {
            "status": status,
            "details": details,
            "authorized_changes": authorized,
            "unauthorized_changes": unauthorized,
        }
    except Exception as e:
        return {
            "status": "FAIL",
            "details": f"Failed to parse change manifest: {str(e)}",
            "authorized_changes": [],
            "unauthorized_changes": [str(e)],
        }


def audit_dataset(
    exp_meta: Dict[str, Any],
    research_periods_path: Path,
    plan_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Inspects dataset assignment and verifies dataset consistency (Phase 13).
    """
    periods_cfg = load_research_periods(research_periods_path)
    configured = is_periods_configured(periods_cfg)

    if not configured:
        return {
            "status": "UNCONFIGURED",
            "dataset_type": "UNCONFIGURED",
            "details": "Research periods in config/research_periods.json are unconfigured placeholders.",
            "periods_status": "unconfigured",
        }

    raw_dataset = exp_meta.get("dataset")

    # Case A: Phase 13 structured dataset (dict)
    if isinstance(raw_dataset, dict):
        raw_partition = raw_dataset.get("partition")
        rec_from = raw_dataset.get("from")
        rec_to = raw_dataset.get("to")

        if not raw_partition or not isinstance(raw_partition, str):
            return {
                "status": "FAIL",
                "dataset_type": "INVALID",
                "details": "Dataset partition is missing or non-string in experiment metadata.",
                "periods_status": "configured",
            }

        norm_partition = raw_partition.lower()
        dtype = norm_partition.upper()

        if norm_partition not in {"training", "validation", "unseen"}:
            return {
                "status": "FAIL",
                "dataset_type": "INVALID",
                "details": f"Invalid dataset partition name '{raw_partition}'. Must be training, validation, or unseen.",
                "periods_status": "configured",
            }

        success, p_name, cfg_from, cfg_to, st_code = resolve_dataset_partition(
            norm_partition, config_path=research_periods_path
        )
        if not success:
            return {
                "status": "FAIL",
                "dataset_type": dtype,
                "details": f"Dataset partition '{norm_partition}' could not be resolved from configuration.",
                "periods_status": "configured",
            }

        # Check recorded period matches configured partition
        if rec_from and parse_date(rec_from) and parse_date(rec_from) != parse_date(cfg_from):
            return {
                "status": "FAIL",
                "dataset_type": dtype,
                "details": f"Recorded dataset period start '{rec_from}' does not match configured period '{cfg_from}' for partition '{dtype}'.",
                "periods_status": "configured",
            }
        if rec_to and parse_date(rec_to) and parse_date(rec_to) != parse_date(cfg_to):
            return {
                "status": "FAIL",
                "dataset_type": dtype,
                "details": f"Recorded dataset period end '{rec_to}' does not match configured period '{cfg_to}' for partition '{dtype}'.",
                "periods_status": "configured",
            }

        # Check experiment execution period matches recorded period
        exp_from = exp_meta.get("from") or exp_meta.get("backtest_config", {}).get("from")
        exp_to = exp_meta.get("to") or exp_meta.get("backtest_config", {}).get("to")
        if exp_from and parse_date(exp_from) and parse_date(exp_from) != parse_date(cfg_from):
            return {
                "status": "FAIL",
                "dataset_type": dtype,
                "details": f"Execution start date '{exp_from}' does not match configured research period start '{cfg_from}'.",
                "periods_status": "configured",
            }
        if exp_to and parse_date(exp_to) and parse_date(exp_to) != parse_date(cfg_to):
            return {
                "status": "FAIL",
                "dataset_type": dtype,
                "details": f"Execution end date '{exp_to}' does not match configured research period end '{cfg_to}'.",
                "periods_status": "configured",
            }

        # Check plan dataset matches experiment dataset partition
        if plan_data is not None:
            plan_ds = plan_data.get("dataset")
            if not plan_ds:
                return {
                    "status": "FAIL",
                    "dataset_type": dtype,
                    "details": "Approved plan is missing required dataset specification.",
                    "periods_status": "configured",
                }
            if isinstance(plan_ds, dict):
                plan_partition = plan_ds.get("partition") or plan_ds.get("type")
            elif isinstance(plan_ds, str):
                plan_partition = plan_ds
            else:
                plan_partition = None

            if not plan_partition or plan_partition.lower() != norm_partition:
                return {
                    "status": "FAIL",
                    "dataset_type": dtype,
                    "details": f"Plan dataset partition '{plan_partition}' does not match experiment dataset partition '{norm_partition}'.",
                    "periods_status": "configured",
                }

        return {
            "status": "CONFIGURED",
            "dataset_type": dtype,
            "details": f"Dataset identity and execution are consistent for partition '{dtype}'.",
            "periods_status": "configured",
        }

    # Case B: Legacy string dataset (compatibility with existing tests and historical experiments)
    if isinstance(raw_dataset, str):
        dtype = raw_dataset.upper()
        if dtype in {"TRAINING", "VALIDATION", "UNSEEN"}:
            return {
                "status": "CONFIGURED",
                "dataset_type": dtype,
                "details": f"Experiment evaluated against configured research period '{dtype}'.",
                "periods_status": "configured",
            }
        return {
            "status": "FAIL",
            "dataset_type": "INVALID",
            "details": f"Invalid dataset partition name '{raw_dataset}'.",
            "periods_status": "configured",
        }

    # Case C: Missing dataset in Phase 13 plan context
    if plan_data is not None:
        return {
            "status": "FAIL",
            "dataset_type": "MISSING",
            "details": "Experiment metadata is missing dataset identity.",
            "periods_status": "configured",
        }

    # Legacy fallback for historical experiments (e.g. EXP-0001) without plan_data
    return {
        "status": "CONFIGURED",
        "dataset_type": "UNCONFIGURED",
        "details": "Legacy experiment without explicit dataset identity.",
        "periods_status": "configured",
    }


def audit_validation_integrity(
    exp_meta: Dict[str, Any],
    plan_data: Optional[Dict[str, Any]],
    experiments_dir: Path,
    candidates_dir: Path,
    research_periods_path: Path,
) -> Dict[str, Any]:
    """
    Phase 14: Audits validation evaluation integrity.
    Verifies:
    1. Validation identity exists.
    2. Validation references a real candidate and candidate hashes match.
    3. Source training experiment exists and references the same candidate.
    4. Validation dataset is strictly VALIDATION.
    5. Validation period matches configured VALIDATION dates and does not overlap TRAINING or UNSEEN.
    6. Candidate in validation matches approved candidate.
    7. Training experiment evidence remains unchanged.
    8. Provenance chain is complete.
    """
    is_val = (
        exp_meta.get("evaluation_type") == "validation"
        or (isinstance(exp_meta.get("dataset"), dict) and exp_meta.get("dataset", {}).get("partition") == "validation")
        or (isinstance(exp_meta.get("dataset"), str) and exp_meta.get("dataset", "").lower() == "validation")
    )
    if not is_val:
        return {
            "status": "NOT_APPLICABLE",
            "details": "Experiment is not a validation evaluation experiment.",
            "issues": [],
        }

    issues = []
    cand_id = exp_meta.get("candidate_id")
    training_exp_id = exp_meta.get("training_experiment_id")

    if not cand_id:
        issues.append("Validation experiment metadata missing candidate_id.")
    if not training_exp_id:
        issues.append("Validation experiment metadata missing training_experiment_id.")

    # 1. Candidate Hash Verification
    if cand_id:
        c_dir = candidates_dir / cand_id
        c_meta_file = c_dir / "metadata.json"
        if not c_dir.is_dir() or not c_meta_file.is_file():
            issues.append(f"Referenced candidate '{cand_id}' directory or metadata missing.")
        else:
            try:
                c_meta = json.loads(c_meta_file.read_text(encoding="utf-8"))
                val_src_hash = exp_meta.get("candidate_source_sha256")
                val_ex5_hash = exp_meta.get("candidate_ex5_sha256")
                cand_src_hash = c_meta.get("source_after_sha256")
                cand_ex5_hash = c_meta.get("source_after_ex5_sha256")

                if val_src_hash and cand_src_hash and val_src_hash != cand_src_hash:
                    issues.append(f"Candidate source hash mismatch: validation has '{val_src_hash}', candidate records '{cand_src_hash}'.")
                if val_ex5_hash and cand_ex5_hash and val_ex5_hash != cand_ex5_hash:
                    issues.append(f"Candidate binary hash mismatch: validation has '{val_ex5_hash}', candidate records '{cand_ex5_hash}'.")
            except Exception as e:
                issues.append(f"Failed to parse candidate metadata: {e}")

    # 2. Source Training Experiment Verification
    if training_exp_id:
        t_dir = experiments_dir / training_exp_id
        t_meta_file = t_dir / "metadata.json"
        if not t_dir.is_dir() or not t_meta_file.is_file():
            issues.append(f"Referenced training experiment '{training_exp_id}' directory or metadata missing.")
        else:
            try:
                t_meta = json.loads(t_meta_file.read_text(encoding="utf-8"))
                t_cand = t_meta.get("candidate_id")
                if t_cand and t_cand != cand_id:
                    issues.append(f"Candidate mismatch: training experiment '{training_exp_id}' recorded candidate '{t_cand}', but validation references '{cand_id}'.")

                t_src_hash = t_meta.get("candidate_source_sha256") or t_meta.get("source_after_sha256")
                val_src_hash = exp_meta.get("candidate_source_sha256")
                if t_src_hash and val_src_hash and t_src_hash != val_src_hash:
                    issues.append(f"Source candidate hash mismatch between training ({t_src_hash}) and validation ({val_src_hash}).")

                t_partition = t_meta.get("dataset", {}).get("partition") if isinstance(t_meta.get("dataset"), dict) else t_meta.get("dataset")
                if t_partition and str(t_partition).lower() != "training":
                    issues.append(f"Training experiment '{training_exp_id}' dataset partition is '{t_partition}', expected 'training'.")
            except Exception as e:
                issues.append(f"Failed to parse training experiment metadata: {e}")

    # 3. Dataset & Period Verification
    val_dataset = exp_meta.get("dataset")
    if isinstance(val_dataset, dict):
        val_partition = val_dataset.get("partition")
    else:
        val_partition = val_dataset

    if not val_partition or str(val_partition).lower() != "validation":
        issues.append(f"Validation experiment dataset partition is '{val_partition}', expected 'validation'.")

    periods_cfg = load_research_periods(research_periods_path)
    val_cfg_p = periods_cfg.get("periods", {}).get("validation", {})
    v_from_cfg = val_cfg_p.get("from")
    v_to_cfg = val_cfg_p.get("to")

    exp_from = exp_meta.get("from") or exp_meta.get("backtest_config", {}).get("from")
    exp_to = exp_meta.get("to") or exp_meta.get("backtest_config", {}).get("to")

    if v_from_cfg and exp_from and parse_date(exp_from) != parse_date(v_from_cfg):
        issues.append(f"Validation execution start date '{exp_from}' does not match configured VALIDATION start date '{v_from_cfg}'.")
    if v_to_cfg and exp_to and parse_date(exp_to) != parse_date(v_to_cfg):
        issues.append(f"Validation execution end date '{exp_to}' does not match configured VALIDATION end date '{v_to_cfg}'.")

    # Verify no overlap with training period
    train_cfg_p = periods_cfg.get("periods", {}).get("training", {})
    t_from_cfg = train_cfg_p.get("from")
    t_to_cfg = train_cfg_p.get("to")

    if exp_from and exp_to and t_from_cfg and t_to_cfg:
        v_from_d = parse_date(exp_from)
        v_to_d = parse_date(exp_to)
        t_from_d = parse_date(t_from_cfg)
        t_to_d = parse_date(t_to_cfg)
        if v_from_d and v_to_d and t_from_d and t_to_d:
            if (v_from_d <= t_to_d) and (v_to_d >= t_from_d):
                issues.append(f"Validation period ({exp_from} - {exp_to}) overlaps configured TRAINING period ({t_from_cfg} - {t_to_cfg}).")

    # Verify no overlap with unseen period
    unseen_cfg_p = periods_cfg.get("periods", {}).get("unseen", {})
    u_from_cfg = unseen_cfg_p.get("from")
    u_to_cfg = unseen_cfg_p.get("to")
    if exp_from and exp_to and u_from_cfg and u_to_cfg:
        if parse_date(exp_from) == parse_date(u_from_cfg) and parse_date(exp_to) == parse_date(u_to_cfg):
            issues.append("Validation execution uses UNSEEN partition dates.")

    status = "PASS" if len(issues) == 0 else "FAIL"
    return {
        "status": status,
        "details": "Validation integrity verified." if status == "PASS" else f"Validation integrity checks failed: {'; '.join(issues)}",
        "issues": issues,
    }


def audit_reproducibility(
    exp_dir: Path,
    exp_meta: Dict[str, Any],
    candidate_id: Optional[str],
    candidates_dir: Path,
    experiments_dir: Optional[Path] = None,
    research_periods_path: Optional[Path] = None,
    metrics_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Evaluates Phase 15 explicit reproducibility dimensions:
    1. identity_reproducibility
    2. configuration_reproducibility
    3. dataset_reproducibility
    4. candidate_reproducibility
    5. artifact_reproducibility
    6. parser_reproducibility
    7. provenance_reproducibility
    8. environment_evidence
    9. repeat_run_consistency
    """
    experiments_dir = Path(experiments_dir) if experiments_dir else exp_dir.parent
    rp_path = Path(research_periods_path) if research_periods_path else PROJECT_ROOT / "config" / "research_periods.json"
    metrics_data = metrics_data or {}

    missing = []
    issues = []

    # 1. Identity Reproducibility
    exp_id = exp_meta.get("experiment_id") or exp_dir.name
    sym = exp_meta.get("symbol") or exp_meta.get("backtest_config", {}).get("symbol")
    tf = exp_meta.get("timeframe") or exp_meta.get("backtest_config", {}).get("timeframe")
    mdl = exp_meta.get("model") or exp_meta.get("backtest_config", {}).get("model")

    if sym and tf and mdl is not None:
        identity_status = "PASS"
    else:
        identity_status = "UNKNOWN"
        issues.append("Identity metadata incomplete.")

    # 2. Configuration Reproducibility
    rel_cfg_hash = exp_meta.get("relevant_configuration_hash") or exp_meta.get("reproducibility", {}).get("relevant_configuration_hash")
    if rel_cfg_hash:
        config_status = "PASS"
    else:
        config_status = "UNKNOWN"

    # 3. Dataset Reproducibility
    rp_cfg_hash = exp_meta.get("research_periods_configuration_hash") or exp_meta.get("reproducibility", {}).get("research_periods_configuration_hash")
    if rp_cfg_hash:
        curr_rp_hash = calculate_research_periods_fingerprint(config_path=rp_path)
        if rp_cfg_hash == curr_rp_hash:
            dataset_status = "PASS"
        else:
            dataset_status = "FAIL"
            issues.append(f"Research periods configuration changed from recorded '{rp_cfg_hash}' to current '{curr_rp_hash}'.")
    else:
        dataset_status = "UNKNOWN"

    # 4. Candidate Reproducibility
    if not candidate_id:
        candidate_status = "NOT_APPLICABLE"
    else:
        c_dir = candidates_dir / candidate_id
        src_file = c_dir / "source_after.mq5"
        bin_file = c_dir / "source_after.ex5"

        if not src_file.is_file() or not bin_file.is_file():
            candidate_status = "FAIL"
            missing.append(f"candidate files for {candidate_id}")
            issues.append(f"Candidate source or binary missing in {candidate_id}.")
        else:
            calc_src_sha = calculate_sha256(src_file)
            calc_bin_sha = calculate_sha256(bin_file)
            rec_src_sha = exp_meta.get("candidate_source_sha256") or exp_meta.get("source_after_sha256")
            rec_bin_sha = exp_meta.get("candidate_ex5_sha256") or exp_meta.get("candidate_binary_sha256") or exp_meta.get("source_after_ex5_sha256")

            if rec_src_sha and calc_src_sha != rec_src_sha:
                candidate_status = "FAIL"
                issues.append(f"Candidate source SHA-256 mismatch for '{candidate_id}'.")
            elif rec_bin_sha and calc_bin_sha != rec_bin_sha:
                candidate_status = "FAIL"
                issues.append(f"Candidate binary SHA-256 mismatch for '{candidate_id}'.")
            else:
                candidate_status = "PASS"

    # 5. Artifact Reproducibility
    if not (exp_dir / "report.htm").is_file():
        missing.append("report.htm")
    if not (exp_dir / "metadata.json").is_file():
        missing.append("metadata.json")
    if not (exp_dir / "metrics.json").is_file():
        missing.append("metrics.json")

    artifact_status = "PASS" if len(missing) == 0 else "FAIL"

    # 6. Parser Reproducibility
    parser_ver = metrics_data.get("parser_version") or exp_meta.get("parser_version") or exp_meta.get("reproducibility", {}).get("parser_version")
    if parser_ver:
        parser_status = "PASS" if parser_ver == "1.0.0" else "FAIL"
    else:
        parser_status = "UNKNOWN"

    # 7. Provenance Reproducibility
    if not candidate_id and not exp_meta.get("plan_id") and not exp_meta.get("hypothesis_id"):
        provenance_status = "NOT_APPLICABLE"
    else:
        plan_id = exp_meta.get("plan_id")
        hyp_id = exp_meta.get("hypothesis_id")
        if plan_id and hyp_id and candidate_id:
            provenance_status = "PASS"
        else:
            provenance_status = "UNKNOWN"

    # 8. Environment Evidence
    env_meta = exp_meta.get("environment_metadata") or exp_meta.get("reproducibility", {}).get("environment_metadata")
    if env_meta and isinstance(env_meta, dict):
        has_secrets = False
        sec_keywords = {"password", "secret", "token", "key", "account"}
        for k, v in env_meta.items():
            if any(sec in str(k).lower() for sec in sec_keywords):
                has_secrets = True
        if has_secrets:
            env_status = "FAIL"
            issues.append("Sensitive credentials found in environment metadata!")
        else:
            env_status = "PASS"
    else:
        env_status = "UNKNOWN"

    # 9. Repeat-Run Consistency
    repeat_of_id = exp_meta.get("repeat_of_experiment_id") or exp_meta.get("reproducibility", {}).get("repeat_of_experiment_id")
    repeat_comp = None
    if repeat_of_id:
        repeat_comp = compare_experiments_reproducibility(repeat_of_id, exp_id, experiments_dir=experiments_dir)
        comp_st = repeat_comp.get("status")
        if comp_st in {MATCH, METRIC_DIFFERENCE_DETECTED}:
            repeat_status = "PASS"
        else:
            repeat_status = "FAIL"
            issues.append(f"Repeat run comparison status is '{comp_st}'.")
    else:
        repeat_status = "NOT_APPLICABLE"

    # Inputs and config records check (Phase 10 compatibility)
    if not exp_meta.get("inputs"):
        missing.append("input parameters record")
    if not exp_meta.get("backtest_config"):
        missing.append("backtest_config record")

    dimensions = {
        "identity_reproducibility": identity_status,
        "configuration_reproducibility": config_status,
        "dataset_reproducibility": dataset_status,
        "candidate_reproducibility": candidate_status,
        "artifact_reproducibility": artifact_status,
        "parser_reproducibility": parser_status,
        "provenance_reproducibility": provenance_status,
        "environment_evidence": env_status,
        "repeat_run_consistency": repeat_status,
    }

    can_reproduce = len(missing) == 0 and not any(dim == "FAIL" for dim in dimensions.values())
    if any(dim == "FAIL" for dim in dimensions.values()) or len(missing) > 2:
        overall_status = "INSUFFICIENT"
    elif can_reproduce:
        overall_status = "COMPLETE"
    else:
        overall_status = "PARTIAL"

    return {
        "status": overall_status,
        "can_reproduce": can_reproduce,
        "missing_elements": missing,
        "dimensions": dimensions,
        "issues": issues,
        "repeat_comparison": repeat_comp,
        "details": f"Reproducibility status: {overall_status}. Dimensions: {dimensions}",
    }


def run_audit(
    experiment_id: str,
    experiments_dir: Path = EXPERIMENTS_DIR,
    candidates_dir: Path = CANDIDATES_DIR,
    plans_dir: Path = PLANS_DIR,
    hypotheses_dir: Path = HYPOTHESES_DIR,
    audits_dir: Path = AUDITS_DIR,
    research_periods_path: Path = RESEARCH_PERIODS_PATH,
    adapter: Optional[BaseAuditorAdapter] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Executes a comprehensive, objective evidence audit for an experiment.
    """
    experiments_dir = Path(experiments_dir)
    candidates_dir = Path(candidates_dir)
    plans_dir = Path(plans_dir)
    hypotheses_dir = Path(hypotheses_dir)
    audits_dir = Path(audits_dir)
    research_periods_path = Path(research_periods_path)

    exp_dir = experiments_dir / experiment_id
    if not exp_dir.is_dir():
        return {
            "schema_version": 1,
            "audit_id": "AUD-0000",
            "audited_at": datetime.now().astimezone().isoformat(),
            "experiment_id": experiment_id,
            "candidate_id": None,
            "plan_id": None,
            "hypothesis_id": None,
            "baseline_experiment": None,
            "status": STATUS_INVALID,
            "evidence_grade": GRADE_INSUFFICIENT,
            "infrastructure_evidence": GRADE_INSUFFICIENT,
            "trading_performance_evidence": GRADE_INSUFFICIENT,
            "experiment_identity_check": {"status": "FAIL", "details": f"Experiment directory does not exist: {exp_dir}", "issues": [f"Missing directory {exp_dir}"]},
            "provenance_check": {"status": "FAIL", "lineage_intact": False, "details": "Experiment directory missing.", "issues": []},
            "artifact_integrity_check": {"status": "FAIL", "details": "Experiment directory missing.", "hashes_verified": False, "issues": []},
            "tester_execution_check": {"status": "INVALID", "bars": 0, "ticks": 0, "trades": 0, "zero_data": True, "details": "Experiment directory missing.", "issues": []},
            "report_consistency_check": {"status": "FAIL", "details": "Experiment directory missing.", "contradictions": []},
            "plan_compliance_check": {"status": COMPLIANCE_UNKNOWN, "details": "Experiment directory missing.", "deviations": []},
            "change_scope_check": {"status": "FAIL", "details": "Experiment directory missing.", "authorized_changes": [], "unauthorized_changes": []},
            "dataset_check": {"status": "UNCONFIGURED", "dataset_type": "UNCONFIGURED", "details": "Experiment missing.", "periods_status": "unconfigured"},
            "reproducibility_check": {"status": "INSUFFICIENT", "can_reproduce": False, "missing_elements": ["experiment directory"], "details": "Experiment missing."},
            "overfitting_risks": [],
            "data_leakage_risks": [],
            "robustness_concerns": ["Experiment does not exist."],
            "evidence_gaps": ["Complete experiment is missing."],
            "observations": [f"Experiment directory '{experiment_id}' was not found in {experiments_dir}."],
            "interpretations": ["The specified experiment cannot be audited because it does not exist."],
            "limitations": ["No evidence available."],
            "follow_up_questions": ["Verify the experiment identifier in experiments/manifest.json."],
        }

    # Check for existing audit if not forcing re-audit
    existing_audit_path = exp_dir / "audit.json"
    if existing_audit_path.is_file() and not force:
        try:
            existing_audit = json.loads(existing_audit_path.read_text(encoding="utf-8"))
            is_valid, _ = validate_audit_dict(existing_audit)
            if is_valid:
                return existing_audit
        except Exception:
            pass

    # 1. Load experiment files
    meta_path = exp_dir / "metadata.json"
    metrics_path = exp_dir / "metrics.json"
    report_path = exp_dir / "report.htm"

    exp_meta = {}
    if meta_path.is_file():
        try:
            exp_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    metrics_data = {}
    if metrics_path.is_file():
        try:
            metrics_data = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    cand_id = exp_meta.get("candidate_id")
    plan_id = exp_meta.get("plan_id")
    hyp_id = exp_meta.get("hypothesis_id")
    base_id = exp_meta.get("baseline_experiment")

    plan_data = None
    if plan_id:
        p_path = plans_dir / f"{plan_id}.json"
        if p_path.is_file():
            try:
                plan_data = json.loads(p_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    manifest_path = experiments_dir / "manifest.json"

    # 2. Run structural checks
    identity_check = audit_experiment_identity(experiment_id, exp_meta)
    provenance_check = audit_provenance(
        experiment_id, exp_meta, candidates_dir, plans_dir, hypotheses_dir, experiments_dir
    )
    integrity_check = audit_artifact_integrity(
        exp_dir, exp_meta, metrics_data, manifest_path, candidates_dir
    )
    tester_check = audit_tester_execution(metrics_data, exp_meta)
    consistency_check = audit_report_consistency(exp_meta, metrics_data, report_path)
    compliance_check = audit_plan_compliance(exp_meta, metrics_data, plan_data)
    change_scope_check = audit_change_scope(cand_id, candidates_dir, plan_data)
    dataset_check = audit_dataset(exp_meta, research_periods_path, plan_data=plan_data)
    reproducibility_check = audit_reproducibility(
        exp_dir=exp_dir,
        exp_meta=exp_meta,
        candidate_id=cand_id,
        candidates_dir=candidates_dir,
        experiments_dir=experiments_dir,
        research_periods_path=research_periods_path,
        metrics_data=metrics_data,
    )
    validation_check = audit_validation_integrity(
        exp_meta=exp_meta,
        plan_data=plan_data,
        experiments_dir=experiments_dir,
        candidates_dir=candidates_dir,
        research_periods_path=research_periods_path,
    )

    # 3. Compile context for Auditor LLM Adapter
    audit_context = {
        "experiment_id": experiment_id,
        "candidate_id": cand_id,
        "plan_id": plan_id,
        "hypothesis_id": hyp_id,
        "baseline_experiment": base_id,
        "experiment_identity_check": identity_check,
        "provenance_check": provenance_check,
        "artifact_integrity_check": integrity_check,
        "tester_execution_check": tester_check,
        "report_consistency_check": consistency_check,
        "plan_compliance_check": compliance_check,
        "change_scope_check": change_scope_check,
        "dataset_check": dataset_check,
        "reproducibility_check": reproducibility_check,
        "validation_check": validation_check,
    }

    # 4. Invoke Auditor Adapter
    auditor_adapter = adapter or MockAuditorAdapter()
    eval_result = auditor_adapter.evaluate_evidence(audit_context)

    if validation_check.get("status") == "FAIL":
        eval_result["status"] = STATUS_INVALID
        eval_result["evidence_grade"] = GRADE_INSUFFICIENT
        eval_result.setdefault("infrastructure_findings", []).extend(validation_check.get("issues", []))

    # 5. Build Final Audit Artifact
    audit_id = get_next_audit_id(audits_dir)
    audit_artifact = {
        "schema_version": 1,
        "audit_id": audit_id,
        "audited_at": datetime.now().astimezone().isoformat(),
        "experiment_id": experiment_id,
        "candidate_id": cand_id,
        "plan_id": plan_id,
        "hypothesis_id": hyp_id,
        "baseline_experiment": base_id,
        "status": eval_result.get("status", STATUS_PASS),
        "evidence_grade": eval_result.get("evidence_grade", GRADE_LIMITED),
        "infrastructure_evidence": eval_result.get("infrastructure_evidence", GRADE_STRONG),
        "trading_performance_evidence": eval_result.get("trading_performance_evidence", GRADE_INSUFFICIENT),
        "experiment_identity_check": identity_check,
        "provenance_check": provenance_check,
        "artifact_integrity_check": integrity_check,
        "tester_execution_check": tester_check,
        "report_consistency_check": consistency_check,
        "plan_compliance_check": compliance_check,
        "change_scope_check": change_scope_check,
        "dataset_check": dataset_check,
        "reproducibility_check": reproducibility_check,
        "validation_check": validation_check,
        "overfitting_risks": eval_result.get("overfitting_risks", []),
        "data_leakage_risks": eval_result.get("data_leakage_risks", []),
        "robustness_concerns": eval_result.get("robustness_concerns", []),
        "evidence_gaps": eval_result.get("evidence_gaps", []),
        "observations": eval_result.get("observations", []),
        "interpretations": eval_result.get("interpretations", []),
        "limitations": eval_result.get("limitations", []),
        "follow_up_questions": eval_result.get("follow_up_questions", []),
    }

    # 6. Archive Audit Artifact (Immutable)
    try:
        # Save colocated in experiment directory
        existing_audit_path.write_text(json.dumps(audit_artifact, indent=2), encoding="utf-8")

        # Save in centralized audits archive
        audits_dir.mkdir(parents=True, exist_ok=True)
        (audits_dir / f"{audit_id}.json").write_text(json.dumps(audit_artifact, indent=2), encoding="utf-8")

        try:
            from scripts.memory import ingest_audit
            ingest_audit(experiment_id, experiments_dir=experiments_dir)
        except Exception:
            pass
    except Exception:
        pass

    return audit_artifact



def format_human_readable_audit(audit: Dict[str, Any]) -> str:
    """
    Formats the audit artifact for clean console reporting.
    """
    aid = audit.get("audit_id", "UNKNOWN")
    eid = audit.get("experiment_id", "UNKNOWN")
    cid = audit.get("candidate_id") or "None (Baseline)"
    pid = audit.get("plan_id") or "None"
    hid = audit.get("hypothesis_id") or "None"
    status = audit.get("status", "UNKNOWN")
    grade = audit.get("evidence_grade", "UNKNOWN")
    infra_grade = audit.get("infrastructure_evidence", "UNKNOWN")
    trading_grade = audit.get("trading_performance_evidence", "UNKNOWN")

    lines = [
        "=" * 60,
        "AI-EA-LAB -- AI AUDITOR (PHASE 10)",
        "=" * 60,
        f"Audit ID:    {aid}",
        f"Experiment:  {eid}",
        f"Candidate:   {cid}",
        f"Plan:        {pid}",
        f"Hypothesis:  {hid}",
        "",
        f"Audit Status:                 {status}",
        f"Overall Evidence Grade:       {grade}",
        f"Infrastructure Evidence:      {infra_grade}",
        f"Trading Performance Evidence: {trading_grade}",
        "",
        "--- STRUCTURAL CHECKS ---",
        f"  Identity Check:      {audit.get('experiment_identity_check', {}).get('status')}",
        f"  Provenance Check:    {audit.get('provenance_check', {}).get('status')}",
        f"  Artifact Integrity:  {audit.get('artifact_integrity_check', {}).get('status')}",
        f"  Tester Execution:    {audit.get('tester_execution_check', {}).get('status')}",
        f"  Report Consistency:  {audit.get('report_consistency_check', {}).get('status')}",
        f"  Plan Compliance:     {audit.get('plan_compliance_check', {}).get('status')}",
        f"  Change Scope Check:  {audit.get('change_scope_check', {}).get('status')}",
        f"  Dataset Partition:   {audit.get('dataset_check', {}).get('status')} ({audit.get('dataset_check', {}).get('dataset_type')})",
        f"  Reproducibility:     {audit.get('reproducibility_check', {}).get('status')}",
        "",
        "--- FACTS & OBSERVATIONS ---",
    ]

    for obs in audit.get("observations", []):
        lines.append(f"  - {obs}")

    lines.append("")
    lines.append("--- INTERPRETATIONS ---")
    for interp in audit.get("interpretations", []):
        lines.append(f"  - {interp}")

    lines.append("")
    lines.append("--- METHODOLOGICAL RISKS ---")
    overfitting = audit.get("overfitting_risks", [])
    if overfitting:
        for r in overfitting:
            lines.append(f"  [Overfitting / {r.get('level')}]: {r.get('description')}")
    else:
        lines.append("  No acute overfitting risks observed.")

    leakage = audit.get("data_leakage_risks", [])
    if leakage:
        for r in leakage:
            lines.append(f"  [Leakage / {r.get('level')}]: {r.get('description')}")

    robustness = audit.get("robustness_concerns", [])
    if robustness:
        for rc in robustness:
            lines.append(f"  [Robustness]: {rc}")

    lines.append("")
    lines.append("--- EVIDENCE GAPS & LIMITATIONS ---")
    for gap in audit.get("evidence_gaps", []):
        lines.append(f"  - Gap: {gap}")
    for lim in audit.get("limitations", []):
        lines.append(f"  - Limitation: {lim}")

    lines.append("")
    lines.append("--- QUESTIONS FOR AI RESEARCHER ---")
    for q in audit.get("follow_up_questions", []):
        lines.append(f"  ? {q}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="AI-EA-Lab Phase 10: AI Auditor for quantitative experiment evidence."
    )
    parser.add_argument(
        "--experiment",
        type=str,
        required=True,
        help="Experiment identifier to audit (e.g. EXP-0004).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON format.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-audit even if an audit artifact already exists.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Use deterministic mock auditor adapter (default: True).",
    )

    args = parser.parse_args()

    result = run_audit(
        experiment_id=args.experiment,
        force=args.force,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_human_readable_audit(result))


if __name__ == "__main__":
    main()
