"""
AI EA Lab - Candidate Synchronization & Staging Module (Phase 9)

Deterministically stages candidate binary (.ex5) into MT5 testing location
under an isolated subfolder (MQL5/Experts/Candidates/CAND-XXXX.ex5).
Ensures:
1. Canonical EA in MQL5/Experts is NEVER overwritten.
2. Source hash and destination hash are cryptographically verified.
3. Provenance and synchronization metadata are recorded.
4. Safe cleanup of staged artifacts if requested.
"""
import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict, Optional


def calculate_file_hash(path: Path) -> str:
    """Calculates SHA-256 hash of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_candidate_binary(
    candidate_id: str,
    source_binary_path: Path,
    mt5_data_dir: Path,
) -> Dict[str, Any]:
    """
    Stages the candidate .ex5 binary into MT5 data directory under MQL5/Experts/Candidates/.
    Verifies that the destination hash matches the source candidate binary hash.
    
    Returns structured synchronization record:
    {
        "candidate_id": str,
        "source_binary": str,
        "destination_binary": str,
        "source_hash": str,
        "destination_hash": str,
        "verified": bool,
        "expert_param": str,
        "error": Optional[str],
    }
    """
    source_binary_path = Path(source_binary_path).resolve()
    mt5_data_dir = Path(mt5_data_dir).resolve()

    if not source_binary_path.is_file():
        return {
            "candidate_id": candidate_id,
            "source_binary": str(source_binary_path),
            "destination_binary": None,
            "source_hash": None,
            "destination_hash": None,
            "verified": False,
            "expert_param": None,
            "error": f"Source candidate binary does not exist: {source_binary_path}",
        }

    source_hash = calculate_file_hash(source_binary_path)

    # Isolated candidate staging directory
    dest_dir = mt5_data_dir / "MQL5" / "Experts" / "Candidates"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{candidate_id}.ex5"

    try:
        # If destination already exists, remove it first to ensure clean state
        if dest_path.exists():
            dest_path.unlink()

        shutil.copy2(source_binary_path, dest_path)
    except Exception as e:
        return {
            "candidate_id": candidate_id,
            "source_binary": str(source_binary_path),
            "destination_binary": str(dest_path),
            "source_hash": source_hash,
            "destination_hash": None,
            "verified": False,
            "expert_param": None,
            "error": f"Failed to copy binary to MT5 destination: {str(e)}",
        }

    destination_hash = calculate_file_hash(dest_path)
    verified = (source_hash == destination_hash)

    # MT5 Strategy Tester expects Expert path relative to MQL5\Experts
    expert_param = f"Candidates\\{candidate_id}.ex5"

    return {
        "candidate_id": candidate_id,
        "source_binary": str(source_binary_path),
        "destination_binary": str(dest_path),
        "source_hash": source_hash,
        "destination_hash": destination_hash,
        "verified": verified,
        "expert_param": expert_param,
        "error": None if verified else "Destination binary hash mismatch with source candidate.",
    }


def cleanup_staged_candidate(destination_binary_path: Path) -> bool:
    """
    Safely cleans up staged candidate binary from MT5 directory.
    """
    try:
        p = Path(destination_binary_path)
        if p.is_file():
            p.unlink()
            return True
    except Exception:
        pass
    return False
