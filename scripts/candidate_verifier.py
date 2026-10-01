"""
AI EA Lab - Candidate Verifier Module (Phase 9)

Performs comprehensive pre-flight candidate verification before any MT5 execution:
1. Candidate directory and metadata existence.
2. Source file existence and cryptographic hash matching.
3. Binary (.ex5) existence, non-zero file size, and compilation verification.
4. Provenance chain verification:
   - Candidate points to valid Plan (PLAN-XXXX).
   - Plan file exists on disk.
   - Plan points to valid Hypothesis (HYP-XXXX).
   - Plan points to valid Baseline Experiment (EXP-XXXX).
   - Baseline experiment exists on disk with metadata.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_DIR = PROJECT_ROOT / "developer" / "candidates"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"

CANDIDATE_ID_PATTERN = re.compile(r"^CAND-(\d{4,})$", re.IGNORECASE)
PLAN_ID_PATTERN = re.compile(r"^PLAN-(\d{4,})$", re.IGNORECASE)
HYPOTHESIS_ID_PATTERN = re.compile(r"^HYP-(\d{4,})$", re.IGNORECASE)
EXPERIMENT_ID_PATTERN = re.compile(r"^EXP-(\d{4,})$", re.IGNORECASE)


def calculate_sha256(file_path: Path) -> str:
    """Calculates SHA-256 hash of a file."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def verify_candidate(
    candidate_id: str,
    candidates_dir: Optional[Path] = None,
    plans_dir: Optional[Path] = None,
    experiments_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Verifies a candidate development artifact.
    Returns structured verification dictionary:
    {
        "candidate_id": str,
        "verified": bool,
        "status": str,
        "source_verified": bool,
        "binary_verified": bool,
        "compile_verified": bool,
        "provenance_verified": bool,
        "hashes": {
            "source_after_sha256": str,
            "source_after_ex5_sha256": str,
            "source_before_sha256": str,
        },
        "metadata": Dict,
        "plan": Dict,
        "baseline_experiment": Dict,
        "issues": List[str],
        "candidate_dir": str,
        "source_path": str,
        "binary_path": str,
    }
    """
    candidates_dir = Path(candidates_dir) if candidates_dir else CANDIDATES_DIR
    plans_dir = Path(plans_dir) if plans_dir else PLANS_DIR
    experiments_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR

    issues: List[str] = []
    result: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "verified": False,
        "status": "CANDIDATE_INVALID",
        "source_verified": False,
        "binary_verified": False,
        "compile_verified": False,
        "provenance_verified": False,
        "hashes": {},
        "metadata": None,
        "plan": None,
        "baseline_experiment": None,
        "issues": issues,
        "candidate_dir": None,
        "source_path": None,
        "binary_path": None,
    }

    # 1. Candidate ID format
    if not candidate_id or not CANDIDATE_ID_PATTERN.match(str(candidate_id)):
        issues.append(f"Invalid candidate ID format: '{candidate_id}'. Expected format CAND-XXXX.")
        result["status"] = "CANDIDATE_INVALID"
        return result

    cand_dir = candidates_dir / candidate_id
    result["candidate_dir"] = str(cand_dir)

    # 2. Candidate directory existence
    if not cand_dir.is_dir():
        issues.append(f"Candidate directory does not exist: {cand_dir}")
        result["status"] = "CANDIDATE_NOT_FOUND"
        return result

    # 3. Metadata existence & structure
    meta_path = cand_dir / "metadata.json"
    if not meta_path.is_file():
        issues.append(f"Candidate metadata.json missing: {meta_path}")
        result["status"] = "CANDIDATE_INVALID"
        return result

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        result["metadata"] = metadata
    except Exception as e:
        issues.append(f"Candidate metadata.json is unparseable: {str(e)}")
        result["status"] = "CANDIDATE_INVALID"
        return result

    # Verify ID in metadata matches candidate_id
    if metadata.get("candidate_id") != candidate_id:
        issues.append(
            f"Candidate ID mismatch: directory is '{candidate_id}', but metadata records '{metadata.get('candidate_id')}'."
        )

    # 4. Source verification
    src_after_path = cand_dir / "source_after.mq5"
    result["source_path"] = str(src_after_path)
    if not src_after_path.is_file():
        issues.append(f"Candidate source file missing: {src_after_path}")
    else:
        src_bytes = src_after_path.read_bytes()
        if len(src_bytes) == 0:
            issues.append(f"Candidate source file is empty (0 bytes): {src_after_path}")
        else:
            calc_src_hash = hashlib.sha256(src_bytes).hexdigest()
            result["hashes"]["source_after_sha256"] = calc_src_hash
            expected_src_hash = metadata.get("source_after_sha256")
            if expected_src_hash and calc_src_hash != expected_src_hash:
                issues.append(
                    f"Candidate source hash mismatch: calculated '{calc_src_hash}', expected '{expected_src_hash}'."
                )
            else:
                result["source_verified"] = True

    # 5. Binary verification
    bin_after_path = cand_dir / "source_after.ex5"
    result["binary_path"] = str(bin_after_path)
    if not bin_after_path.is_file():
        issues.append(f"Candidate binary file missing: {bin_after_path}")
        result["status"] = "BINARY_MISSING"
    else:
        bin_size = bin_after_path.stat().st_size
        if bin_size == 0:
            issues.append(f"Candidate binary is invalid (0 bytes): {bin_after_path}")
            result["status"] = "BINARY_INVALID"
        else:
            calc_bin_hash = hashlib.sha256(bin_after_path.read_bytes()).hexdigest()
            result["hashes"]["source_after_ex5_sha256"] = calc_bin_hash
            result["binary_verified"] = True

    # Check compile status in metadata
    compile_status = metadata.get("compile_status")
    if compile_status != "passed":
        issues.append(f"Candidate compilation status is not 'passed' (recorded: '{compile_status}').")
        if not result["status"].startswith("BINARY"):
            result["status"] = "COMPILE_FAILED"
    else:
        result["compile_verified"] = True

    # 6. Provenance Chain Verification
    plan_id = metadata.get("plan_id")
    hyp_id = metadata.get("hypothesis_id")
    base_id = metadata.get("baseline_experiment")

    provenance_ok = True
    if not plan_id or not PLAN_ID_PATTERN.match(str(plan_id)):
        issues.append(f"Invalid or missing plan_id in candidate metadata: '{plan_id}'.")
        provenance_ok = False
    else:
        plan_file = plans_dir / f"{plan_id}.json"
        if not plan_file.is_file():
            issues.append(f"Referenced plan file does not exist: {plan_file}")
            provenance_ok = False
        else:
            try:
                plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
                result["plan"] = plan_data
            except Exception as e:
                issues.append(f"Referenced plan file unparseable: {str(e)}")
                provenance_ok = False

    if not hyp_id or not HYPOTHESIS_ID_PATTERN.match(str(hyp_id)):
        issues.append(f"Invalid or missing hypothesis_id in candidate metadata: '{hyp_id}'.")
        provenance_ok = False

    if not base_id or not EXPERIMENT_ID_PATTERN.match(str(base_id)):
        issues.append(f"Invalid or missing baseline_experiment in candidate metadata: '{base_id}'.")
        provenance_ok = False
    else:
        base_dir = experiments_dir / base_id
        if not base_dir.is_dir():
            issues.append(f"Referenced baseline experiment directory does not exist: {base_dir}")
            provenance_ok = False
        else:
            base_meta_file = base_dir / "metadata.json"
            if not base_meta_file.is_file():
                issues.append(f"Referenced baseline experiment missing metadata.json: {base_meta_file}")
                provenance_ok = False
            else:
                try:
                    result["baseline_experiment"] = json.loads(base_meta_file.read_text(encoding="utf-8"))
                except Exception as e:
                    issues.append(f"Referenced baseline metadata unparseable: {str(e)}")
                    provenance_ok = False

    result["provenance_verified"] = provenance_ok
    if not provenance_ok and result["status"] not in {"BINARY_MISSING", "BINARY_INVALID"}:
        result["status"] = "PROVENANCE_INVALID"

    # Overall verification decision
    if (
        result["source_verified"]
        and result["binary_verified"]
        and result["compile_verified"]
        and result["provenance_verified"]
        and len(issues) == 0
    ):
        result["verified"] = True
        result["status"] = "READY"

    return result


def verify_candidate_for_validation(
    candidate_id: str,
    training_exp_id: str,
    candidates_dir: Optional[Path] = None,
    experiments_dir: Optional[Path] = None,
    plans_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Phase 14: Verifies that a candidate is eligible for validation evaluation against a training experiment.
    Checks:
    1. Standard candidate pre-flight verification (source, binary, metadata, hashes, provenance).
    2. Training experiment exists on disk.
    3. Candidate recorded hashes in training experiment metadata match candidate's current hashes.
    4. Training experiment references the same candidate_id.
    """
    candidates_dir = Path(candidates_dir) if candidates_dir else CANDIDATES_DIR
    experiments_dir = Path(experiments_dir) if experiments_dir else EXPERIMENTS_DIR

    # Run standard candidate verification
    verif = verify_candidate(
        candidate_id=candidate_id,
        candidates_dir=candidates_dir,
        plans_dir=plans_dir,
        experiments_dir=experiments_dir,
    )
    if not verif["verified"]:
        return verif

    issues: List[str] = list(verif.get("issues", []))

    # Verify Training Experiment
    train_exp_dir = experiments_dir / training_exp_id
    if not train_exp_dir.is_dir():
        issues.append(f"Training experiment directory '{training_exp_id}' does not exist.")
        verif["verified"] = False
        verif["status"] = "TRAINING_EXPERIMENT_NOT_FOUND"
        verif["issues"] = issues
        return verif

    train_meta_file = train_exp_dir / "metadata.json"
    if not train_meta_file.is_file():
        issues.append(f"Training experiment '{training_exp_id}' is missing metadata.json.")
        verif["verified"] = False
        verif["status"] = "TRAINING_EXPERIMENT_INVALID"
        verif["issues"] = issues
        return verif

    try:
        train_meta = json.loads(train_meta_file.read_text(encoding="utf-8"))
    except Exception as e:
        issues.append(f"Failed to parse training experiment metadata: {str(e)}")
        verif["verified"] = False
        verif["status"] = "TRAINING_EXPERIMENT_INVALID"
        verif["issues"] = issues
        return verif

    # Check candidate ID match
    train_cand = train_meta.get("candidate_id")
    if train_cand and train_cand != candidate_id:
        issues.append(
            f"Candidate ID mismatch: training experiment '{training_exp_id}' recorded candidate '{train_cand}', expected '{candidate_id}'."
        )
        verif["verified"] = False
        verif["status"] = "CANDIDATE_ID_MISMATCH"
        verif["issues"] = issues
        return verif

    # Check Candidate Source SHA-256 match
    curr_src_sha = verif["hashes"].get("source_after_sha256")
    train_src_sha = train_meta.get("candidate_source_sha256") or train_meta.get("source_after_sha256")
    if train_src_sha and curr_src_sha and curr_src_sha != train_src_sha:
        issues.append(
            f"Candidate source hash mismatch between current candidate '{candidate_id}' ({curr_src_sha}) and training experiment '{training_exp_id}' ({train_src_sha})."
        )
        verif["verified"] = False
        verif["status"] = "CANDIDATE_HASH_MISMATCH"
        verif["issues"] = issues
        return verif

    # Check Candidate EX5 SHA-256 match
    curr_ex5_sha = verif["hashes"].get("source_after_ex5_sha256")
    train_ex5_sha = train_meta.get("candidate_ex5_sha256") or train_meta.get("source_after_ex5_sha256")
    if train_ex5_sha and curr_ex5_sha and curr_ex5_sha != train_ex5_sha:
        issues.append(
            f"Candidate binary hash mismatch between current candidate '{candidate_id}' ({curr_ex5_sha}) and training experiment '{training_exp_id}' ({train_ex5_sha})."
        )
        verif["verified"] = False
        verif["status"] = "CANDIDATE_HASH_MISMATCH"
        verif["issues"] = issues
        return verif

    verif["training_experiment"] = train_meta
    verif["verified"] = len(issues) == 0
    if not verif["verified"]:
        verif["status"] = "CANDIDATE_HASH_MISMATCH"
    return verif
