"""
MQL5 Compiler Interface

Discovers installed MetaEditor compiler, compiles MQL5 candidate source code,
captures raw compiler logs and parsed error/warning messages, and verifies
binary (.ex5) generation.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

RESULT_LINE_PATTERN = re.compile(
    r"Result:\s*(\d+)\s+errors?,\s*(\d+)\s+warnings?",
    re.IGNORECASE
)


def find_metaeditor(config_path: Optional[Path] = None) -> Optional[Path]:
    """
    Discovers the MetaEditor 64-bit/32-bit executable.
    Checks:
    1. config.json mt5_terminal directory
    2. Common MT5 installation directories
    3. System PATH
    """
    candidates = []

    # 1. Check directory of mt5_terminal in config.json
    if config_path and Path(config_path).is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            term = cfg.get("mt5_terminal")
            if term:
                term_dir = Path(term).parent
                candidates.extend([
                    term_dir / "metaeditor64.exe",
                    term_dir / "metaeditor.exe",
                ])
        except Exception:
            pass

    # 2. Common Windows installation paths
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidates.extend([
        Path(program_files) / "MetaTrader 5" / "metaeditor64.exe",
        Path(program_files) / "MetaTrader 5" / "metaeditor.exe",
        Path(program_files_x86) / "MetaTrader 5" / "metaeditor64.exe",
        Path(program_files_x86) / "MetaTrader 5" / "metaeditor.exe",
    ])

    for cand in candidates:
        if cand.is_file():
            return cand.resolve()

    # 3. Check PATH
    which_path = shutil.which("metaeditor64") or shutil.which("metaeditor")
    if which_path:
        return Path(which_path).resolve()

    return None


def read_compile_log(log_path: Path) -> str:
    """
    Safely reads compiler log with fallback across UTF-16, UTF-16LE, UTF-8, and Latin-1.
    """
    if not log_path.is_file():
        return ""

    raw = log_path.read_bytes()
    for enc in ["utf-16", "utf-16le", "utf-8", "latin-1"]:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_compiler_output(log_text: str) -> Tuple[int, int, List[str], List[str]]:
    """
    Parses compiler output log for error count, warning count, and message lines.
    Returns (error_count, warning_count, errors_list, warnings_list).
    """
    errors: List[str] = []
    warnings: List[str] = []
    total_errors = 0
    total_warnings = 0

    lines = log_text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        result_match = RESULT_LINE_PATTERN.search(stripped)
        if result_match:
            total_errors = int(result_match.group(1))
            total_warnings = int(result_match.group(2))
            continue

        lower = stripped.lower()
        if ": error" in lower or "error " in lower:
            errors.append(stripped)
        elif ": warning" in lower or "warning " in lower:
            warnings.append(stripped)

    # If result line was not found but error lines exist
    if total_errors == 0 and errors:
        total_errors = len(errors)
    if total_warnings == 0 and warnings:
        total_warnings = len(warnings)

    return total_errors, total_warnings, errors, warnings


def compile_mql5(
    source_path: Path,
    output_dir: Optional[Path] = None,
    compiler_path: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Compiles an MQL5 source file using MetaEditor.
    
    Returns structured compilation report:
    {
        "status": "passed" | "failed" | "unavailable",
        "compiler_path": str,
        "command": str,
        "exit_code": int,
        "error_count": int,
        "warning_count": int,
        "errors": List[str],
        "warnings": List[str],
        "binary_path": Optional[str],
        "log_path": Optional[str],
        "log_content": str,
    }
    """
    source_path = Path(source_path).resolve()
    if not source_path.is_file():
        return {
            "status": "failed",
            "compiler_path": None,
            "command": "",
            "exit_code": -1,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"Source file does not exist: {source_path}"],
            "warnings": [],
            "binary_path": None,
            "log_path": None,
            "log_content": "",
        }

    metaeditor = compiler_path or find_metaeditor()
    if not metaeditor or not Path(metaeditor).is_file():
        return {
            "status": "unavailable",
            "compiler_path": None,
            "command": "",
            "exit_code": -1,
            "error_count": 0,
            "warning_count": 1,
            "errors": [],
            "warnings": ["MetaEditor compiler (metaeditor64.exe) not found on system."],
            "binary_path": None,
            "log_path": None,
            "log_content": "Compilation skipped: MetaEditor compiler not found.",
        }

    out_dir = Path(output_dir) if output_dir else source_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "compile.log"

    # MetaEditor CLI command:
    # metaeditor64.exe /compile:"path\to\file.mq5" /log:"path\to\compile.log"
    cmd = [
        str(metaeditor),
        f"/compile:{str(source_path)}",
        f"/log:{str(log_path)}",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "compiler_path": str(metaeditor),
            "command": " ".join(cmd),
            "exit_code": -2,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"Compilation timed out after {timeout_seconds} seconds."],
            "warnings": [],
            "binary_path": None,
            "log_path": str(log_path) if log_path.is_file() else None,
            "log_content": "Timeout expired during compilation.",
        }
    except Exception as e:
        return {
            "status": "failed",
            "compiler_path": str(metaeditor),
            "command": " ".join(cmd),
            "exit_code": -3,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"Execution error running MetaEditor: {str(e)}"],
            "warnings": [],
            "binary_path": None,
            "log_path": None,
            "log_content": str(e),
        }

    log_content = read_compile_log(log_path)
    err_count, warn_count, errors, warnings = parse_compiler_output(log_content)

    # Check for expected .ex5 binary beside source_path
    expected_ex5 = source_path.with_suffix(".ex5")
    binary_path = None
    if expected_ex5.is_file() and expected_ex5.stat().st_size > 0:
        binary_path = str(expected_ex5.resolve())

    status = "passed" if (err_count == 0 and binary_path is not None) else "failed"

    return {
        "status": status,
        "compiler_path": str(metaeditor),
        "command": " ".join(cmd),
        "exit_code": exit_code,
        "error_count": err_count,
        "warning_count": warn_count,
        "errors": errors,
        "warnings": warnings,
        "binary_path": binary_path,
        "log_path": str(log_path),
        "log_content": log_content,
    }
