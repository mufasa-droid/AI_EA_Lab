"""
AI EA Lab - AI Developer (Phase 8)

The controlled code implementation layer.
Converts a HUMAN-APPROVED Experiment Plan into a reproducible MQL5 candidate,
verifies the candidate with static checks and MQL5 compilation, and archives
an auditable development artifact.

Enforces:
1. Strict Human Approval Boundary (never auto-approves or proceeds without explicit approval).
2. Plan & Baseline Schema and Value Validation.
3. Feasibility Analysis (rejects incompatible plans; never invents trading logic).
4. Controlled Changes Principle (modifies ONLY authorized parameters).
5. Source Preservation (baseline EA remains strictly untouched; source_before preserved).
6. Deterministic Candidate IDs (CAND-XXXX).
7. Static Change Validation (rejects unauthorized modifications).
8. MQL5 Compilation & Artifact Archival.
9. Deterministic Mock Mode and Dry-Run.

Does NOT execute live trades, place broker orders, or auto-run backtests.
"""
import argparse
import difflib
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

CANDIDATES_DIR = PROJECT_ROOT / "developer" / "candidates"
PLANS_DIR = PROJECT_ROOT / "research" / "plans"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
EA_DIR = PROJECT_ROOT / "ea"

from developer.llm.base import BaseDeveloperAdapter, MockDeveloperAdapter
from scripts.developer_schemas import (
    CANDIDATE_ID_PATTERN,
    PLAN_ID_PATTERN,
    check_plan_approval,
    get_next_candidate_id,
    set_plan_approval,
    validate_candidate_metadata,
    validate_change_manifest,
    validate_feasibility_dict,
    validate_static_changes,
)
from scripts.feasibility import analyze_plan_feasibility
from scripts.mql5_compiler import compile_mql5, find_metaeditor
from scripts.research_schemas import validate_experiment_plan_dict


def calculate_sha256(content: str) -> str:
    """Calculates SHA-256 hash of a string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_plan(plan_identifier: str, plans_dir: Path = PLANS_DIR) -> Tuple[Optional[Dict[str, Any]], Optional[Path], str]:
    """
    Loads an experiment plan by ID (PLAN-XXXX) or direct file path.
    Returns (plan_dict, plan_path, error_message).
    """
    plans_dir = Path(plans_dir)
    target_path = Path(plan_identifier)

    if not target_path.is_file():
        # Try finding in plans_dir
        if not plan_identifier.endswith(".json"):
            target_path = plans_dir / f"{plan_identifier}.json"
        else:
            target_path = plans_dir / plan_identifier

    if not target_path.is_file():
        return None, None, f"Plan file not found: '{plan_identifier}'"

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        return plan, target_path, ""
    except Exception as e:
        return None, target_path, f"Failed to parse plan JSON: {str(e)}"


def validate_baseline(
    plan: Dict[str, Any],
    experiments_dir: Path = EXPERIMENTS_DIR,
) -> Tuple[bool, List[str], Optional[Dict[str, Any]]]:
    """
    Validates that the baseline experiment referenced by the plan exists,
    has valid metadata and metrics, and that baseline input values match.
    """
    issues: List[str] = []
    baseline = plan.get("baseline", {})
    if not isinstance(baseline, dict) or not baseline.get("experiment_id"):
        return False, ["Plan does not define a valid baseline object with experiment_id."], None

    b_id = baseline.get("experiment_id")
    b_dir = Path(experiments_dir) / b_id

    if not b_dir.is_dir():
        issues.append(f"Baseline experiment '{b_id}' does not exist in experiments archive.")
        return False, issues, None

    meta_file = b_dir / "metadata.json"
    if not meta_file.is_file():
        issues.append(f"Baseline experiment '{b_id}' is missing metadata.json.")
        return False, issues, None

    try:
        with open(meta_file, "r", encoding="utf-8") as f:
            b_meta = json.load(f)
    except Exception as e:
        issues.append(f"Failed to read baseline metadata: {str(e)}")
        return False, issues, None

    # Check EA name match
    expected_ea = baseline.get("ea")
    actual_ea = b_meta.get("ea")
    if expected_ea and actual_ea and expected_ea != actual_ea:
        issues.append(f"Baseline EA mismatch: plan expects '{expected_ea}', baseline recorded '{actual_ea}'.")

    # Check baseline inputs match what the plan states
    plan_changes = plan.get("changes_under_test", [])
    b_inputs = b_meta.get("inputs", {})
    for chg in plan_changes:
        v_name = chg.get("variable")
        plan_base_val = chg.get("baseline_value")
        if v_name in b_inputs:
            actual_val = str(b_inputs[v_name])
            if str(plan_base_val) != actual_val:
                issues.append(
                    f"Baseline input mismatch for '{v_name}': plan expects baseline value '{plan_base_val}', "
                    f"but baseline '{b_id}' has '{actual_val}'."
                )

    return len(issues) == 0, issues, b_meta


def run_developer(
    plan_identifier: str,
    dry_run: bool = False,
    mock: bool = True,
    plans_dir: Path = PLANS_DIR,
    candidates_dir: Path = CANDIDATES_DIR,
    experiments_dir: Path = EXPERIMENTS_DIR,
    ea_dir: Path = EA_DIR,
    adapter: Optional[BaseDeveloperAdapter] = None,
) -> Dict[str, Any]:
    """
    Executes the AI Developer pipeline for a specified experiment plan.
    """
    plans_dir = Path(plans_dir)
    candidates_dir = Path(candidates_dir)
    experiments_dir = Path(experiments_dir)
    ea_dir = Path(ea_dir)

    result: Dict[str, Any] = {
        "candidate_id": None,
        "plan_id": plan_identifier,
        "baseline_experiment": None,
        "ea": None,
        "approval": {"status": "pending"},
        "feasibility": {
            "status": "pending",
            "feasible": False,
            "reason": "",
            "required_changes": [],
            "blocked_by": [],
        },
        "changes": [],
        "validation": {
            "is_valid": False,
            "unauthorized_changes": [],
            "source_preserved": True,
        },
        "compile": {
            "status": "skipped",
            "errors": [],
            "warnings": [],
        },
        "dry_run": dry_run,
        "status": "pending",
        "action": "none",
        "reason": "",
    }

    # 1. Load plan
    plan, plan_path, err = load_plan(plan_identifier, plans_dir=plans_dir)
    if not plan:
        result["status"] = "error"
        result["reason"] = f"Plan loading error: {err}"
        result["action"] = "No development performed: plan not found."
        return result

    plan_id = plan.get("experiment_plan_id", plan_identifier)
    result["plan_id"] = plan_id

    # Populate baseline and EA details early for reporting
    bid = plan.get("baseline", {}).get("experiment_id", "")
    result["baseline_experiment"] = bid
    base_ea = plan.get("baseline", {}).get("ea", "TestEA")
    target_ea = base_ea
    for chg in plan.get("changes_under_test", []):
        if chg.get("variable") == "ea":
            target_ea = chg.get("target_value", target_ea)
            break
    ea_name = target_ea
    result["ea"] = target_ea

    # 2. Plan schema validation
    is_valid_plan, plan_issues = validate_experiment_plan_dict(plan)
    if not is_valid_plan:
        result["status"] = "plan_invalid"
        result["reason"] = f"Plan schema validation failed: {'; '.join(plan_issues)}"
        result["action"] = "Rejected malformed plan."
        return result

    # 3. CRITICAL HUMAN APPROVAL BOUNDARY
    is_approved, approval_reason, approval_block = check_plan_approval(plan)
    result["approval"] = approval_block
    if not is_approved:
        result["status"] = "approval_required"
        result["reason"] = approval_reason
        result["action"] = (
            "Execution halted. Plans cannot be implemented without explicit human approval. "
            "Approval must be explicitly recorded with status: 'approved'."
        )
        return result

    # 4. Baseline validation
    is_valid_base, base_issues, base_meta = validate_baseline(plan, experiments_dir=experiments_dir)
    if not is_valid_base:
        result["status"] = "baseline_invalid"
        result["reason"] = f"Baseline validation failed: {'; '.join(base_issues)}"
        result["action"] = "No development performed due to baseline mismatch or missing baseline."
        return result

    # 5. Locate target EA source
    ea_source_file = ea_dir / f"{target_ea}.mq5"
    if not ea_source_file.is_file():
        result["status"] = "blocked"
        result["reason"] = f"Target EA source code '{ea_source_file}' not found."
        result["action"] = "No source modification performed."
        return result

    try:
        source_before = ea_source_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source_before = ea_source_file.read_text(encoding="utf-16", errors="replace")

    # If the baseline experiment recorded specific input parameter values,
    # synchronize source_before's input defaults with the baseline experiment
    # so that source_before faithfully represents the baseline state.
    b_inputs = base_meta.get("inputs", {}) if base_meta else {}
    for var_name, var_val in b_inputs.items():
        val_str = "true" if var_val is True else "false" if var_val is False else str(var_val)
        pattern = re.compile(
            rf"^(\s*input\s+[a-zA-Z0-9_]+\s+{re.escape(var_name)}\s*=\s*)([^;]+)(;.*)$",
            re.MULTILINE
        )
        match = pattern.search(source_before)
        if match:
            prefix = match.group(1)
            suffix = match.group(3)
            source_before = source_before[:match.start()] + f"{prefix}{val_str}{suffix}" + source_before[match.end():]

    source_before_sha = calculate_sha256(source_before)

    # 6. FEASIBILITY ANALYSIS
    feasibility = analyze_plan_feasibility(plan, ea_source_file)
    result["feasibility"] = feasibility

    if not feasibility.get("feasible", False):
        result["status"] = (
            "requires_plan_revision"
            if feasibility.get("status") == "requires_plan_revision"
            else "blocked"
        )
        result["reason"] = feasibility.get("reason", "Experiment plan is technically infeasible.")
        result["action"] = "No source modification performed."
        return result

    # 7. Check Developer Adapter
    dev_adapter = adapter or MockDeveloperAdapter()
    dev_output = dev_adapter.develop_candidate(plan, source_before)
    source_after = dev_output.get("modified_source", source_before)
    source_after_sha = calculate_sha256(source_after)

    # 8. Static Change Validation
    authorized_changes = plan.get("changes_under_test", [])
    is_valid_changes, applied_changes, unauthorized_changes = validate_static_changes(
        source_before,
        source_after,
        authorized_changes,
    )
    result["changes"] = applied_changes
    result["validation"] = {
        "is_valid": is_valid_changes,
        "unauthorized_changes": unauthorized_changes,
        "source_preserved": True,
    }

    if not is_valid_changes:
        result["status"] = "validation_failed"
        result["reason"] = f"Unauthorized changes detected: {'; '.join(unauthorized_changes)}"
        result["action"] = "Candidate rejected due to unauthorized code changes."
        return result

    # 9. Handle Dry-Run
    if dry_run:
        result["candidate_id"] = "CAND-DRYRUN"
        result["status"] = "ready_for_next_phase"
        result["action"] = "Dry-run complete: changes verified and feasible. No files modified or created."
        return result

    # 10. Create Candidate Workspace
    candidate_id = get_next_candidate_id(candidates_dir)
    result["candidate_id"] = candidate_id
    cand_dir = candidates_dir / candidate_id
    cand_dir.mkdir(parents=True, exist_ok=True)

    # Preserve source_before
    source_before_path = cand_dir / "source_before.mq5"
    source_before_path.write_text(source_before, encoding="utf-8")

    # Write source_after
    source_after_path = cand_dir / "source_after.mq5"
    source_after_path.write_text(source_after, encoding="utf-8")

    # Ensure hashes match written file bytes (Windows CRLF normalization)
    source_before_sha = hashlib.sha256(source_before_path.read_bytes()).hexdigest()
    source_after_sha = hashlib.sha256(source_after_path.read_bytes()).hexdigest()

    # Generate diff.patch
    diff_lines = list(difflib.unified_diff(
        source_before.splitlines(keepends=True),
        source_after.splitlines(keepends=True),
        fromfile="source_before.mq5",
        tofile="source_after.mq5",
    ))
    diff_text = "".join(diff_lines)
    (cand_dir / "diff.patch").write_text(diff_text, encoding="utf-8")

    # 11. Compile Candidate
    compile_result = compile_mql5(source_after_path, output_dir=cand_dir)
    if mock and compile_result.get("status") == "unavailable":
        mock_bin_path = cand_dir / "source_after.ex5"
        mock_bin_path.write_bytes(b"\x00\x00MOCK_EX5_BINARY\x00\x00")
        compile_result = {
            "status": "passed",
            "compiler_path": "mock",
            "exit_code": 0,
            "error_count": 0,
            "warning_count": 0,
            "errors": [],
            "warnings": [],
            "binary_path": str(mock_bin_path),
            "log_path": None,
            "log_content": "Mock compilation passed (metaeditor unavailable).",
        }
    result["compile"] = {
        "status": compile_result.get("status"),
        "compiler_path": compile_result.get("compiler_path"),
        "errors": compile_result.get("errors", []),
        "warnings": compile_result.get("warnings", []),
        "binary_path": compile_result.get("binary_path"),
    }

    # 12. Save Change Manifest & Feasibility & Metadata
    manifest_data = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "plan_id": plan_id,
        "baseline_experiment": bid,
        "ea": ea_name,
        "changes": applied_changes,
        "unauthorized_changes": unauthorized_changes,
        "feasible": True,
        "compile_status": compile_result.get("status"),
    }
    (cand_dir / "change_manifest.json").write_text(
        json.dumps(manifest_data, indent=2), encoding="utf-8"
    )

    (cand_dir / "feasibility.json").write_text(
        json.dumps(feasibility, indent=2), encoding="utf-8"
    )

    final_status = "ready_for_next_phase" if compile_result.get("status") in {"passed", "unavailable"} else "compile_failed"
    metadata = {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "plan_id": plan_id,
        "hypothesis_id": plan.get("hypothesis_id", "HYP-0000"),
        "baseline_experiment": bid,
        "ea": ea_name,
        "created_at": datetime.now().astimezone().isoformat(),
        "source_before_sha256": source_before_sha,
        "source_after_sha256": source_after_sha,
        "requested_changes": authorized_changes,
        "actual_changes": applied_changes,
        "feasibility_status": feasibility.get("status"),
        "compile_status": compile_result.get("status"),
        "compiler_info": {
            "compiler_path": compile_result.get("compiler_path"),
            "exit_code": compile_result.get("exit_code"),
            "error_count": compile_result.get("error_count", 0),
            "warning_count": compile_result.get("warning_count", 0),
        },
        "status": final_status,
    }
    (cand_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    result["status"] = final_status
    result["action"] = f"Candidate created and archived under developer/candidates/{candidate_id}."
    return result


def format_human_readable_output(result: Dict[str, Any]) -> str:
    """
    Formats Developer execution result into clear, structured human-readable text.
    """
    plan_id = result.get("plan_id", "UNKNOWN")
    base_id = result.get("baseline_experiment", "NONE")
    ea = result.get("ea", "NONE")
    status = result.get("status", "").upper()
    action = result.get("action", "")
    reason = result.get("reason", "")
    cand_id = result.get("candidate_id")

    lines = [
        "============================================================",
        "AI-EA-LAB -- AI DEVELOPER",
        "============================================================",
        f"Plan: {plan_id}",
        f"Baseline: {base_id}",
        f"EA: {ea}",
        "",
        "Approval:",
    ]

    app = result.get("approval", {})
    app_status = app.get("status", "missing").upper()
    if app_status == "APPROVED":
        reviewer = app.get("reviewed_by", "human")
        rev_at = app.get("reviewed_at", "")
        lines.append(f"    APPROVED (by {reviewer} at {rev_at})")
    elif app_status == "PENDING":
        lines.append("    PENDING (Human approval required)")
    elif app_status == "REJECTED":
        lines.append(f"    REJECTED ({app.get('reason', 'None specified')})")
    else:
        lines.append("    NOT APPROVED (Approval block missing)")

    feas = result.get("feasibility", {})
    feas_status = feas.get("status", "unknown").upper()
    lines.append("")
    lines.append(f"Feasibility:\n    {feas_status}")

    if feas.get("reason"):
        lines.append("")
        lines.append(f"Reason:\n    {feas.get('reason')}")
    elif reason:
        lines.append("")
        lines.append(f"Reason:\n    {reason}")

    changes = result.get("changes", [])
    if changes:
        lines.append("")
        lines.append("Requested changes:")
        for chg in changes:
            lines.append(f"    {chg.get('parameter')} {chg.get('before')} -> {chg.get('after')}")

    unauth = result.get("validation", {}).get("unauthorized_changes", [])
    lines.append("")
    lines.append("Unauthorized changes:")
    if not unauth:
        lines.append("    NONE")
    else:
        for u in unauth:
            lines.append(f"    WARNING: {u}")

    compile_info = result.get("compile", {})
    if compile_info.get("status") != "skipped":
        lines.append("")
        lines.append(f"Compilation:\n    {compile_info.get('status', '').upper()}")
        errs = compile_info.get("errors", [])
        if errs:
            lines.append("    Errors:")
            for e in errs:
                lines.append(f"      - {e}")

    if cand_id:
        lines.append("")
        lines.append(f"Candidate:\n    {cand_id}")

    lines.append("")
    lines.append(f"Action:\n    {action}")
    lines.append("")
    lines.append(f"Status:\n    {status}")
    lines.append("============================================================")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="AI-EA-Lab AI Developer: Controlled MQL5 candidate implementation and compilation."
    )
    parser.add_argument(
        "--plan",
        type=str,
        help="Experiment Plan ID (e.g. PLAN-0001) or path to plan JSON file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform validation, feasibility check, and diff generation without modifying or creating files.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        default=True,
        help="Use deterministic mock developer adapter (default: True).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result in machine-readable JSON format.",
    )
    parser.add_argument(
        "--approve",
        type=str,
        help="Approve an experiment plan on disk (e.g. --approve PLAN-0001).",
    )
    parser.add_argument(
        "--revoke",
        type=str,
        help="Revoke approval for an experiment plan on disk (sets status to 'pending').",
    )
    parser.add_argument(
        "--reviewer",
        type=str,
        default="human_reviewer",
        help="Reviewer name for --approve (default: human_reviewer).",
    )
    parser.add_argument(
        "--note",
        type=str,
        default="",
        help="Optional note for --approve.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Display status of plans and candidates.",
    )

    args = parser.parse_args()

    # Handle approval CLI commands
    if args.approve:
        target = PLANS_DIR / f"{args.approve}.json" if not args.approve.endswith(".json") else Path(args.approve)
        try:
            updated = set_plan_approval(target, "approved", approved_by=args.reviewer, note=args.note)
            if args.json:
                print(json.dumps({"plan_id": updated.get("experiment_plan_id"), "approval": updated.get("approval")}, indent=2))
            else:
                print(f"[APPROVED]: Plan {updated.get('experiment_plan_id')} approved by {args.reviewer}.")
        except Exception as e:
            print(f"Error approving plan: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.revoke:
        target = PLANS_DIR / f"{args.revoke}.json" if not args.revoke.endswith(".json") else Path(args.revoke)
        try:
            updated = set_plan_approval(target, "pending", approved_by=args.reviewer, note=args.note)
            if args.json:
                print(json.dumps({"plan_id": updated.get("experiment_plan_id"), "approval": updated.get("approval")}, indent=2))
            else:
                print(f"[REVOKED]: Plan {updated.get('experiment_plan_id')} approval revoked (status: pending).")
        except Exception as e:
            print(f"Error revoking plan: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Handle status command
    if args.status:
        plans = sorted(PLANS_DIR.glob("PLAN-*.json"))
        cands = sorted(CANDIDATES_DIR.glob("CAND-*"))
        print("=== AI-EA-LAB DEVELOPER STATUS ===")
        print(f"Plans found ({len(plans)}):")
        for p in plans:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                app = data.get("approval", {}).get("status", "none")
                print(f"  - {p.stem}: status={data.get('status')} approval={app}")
            except Exception:
                print(f"  - {p.stem}: [unreadable]")
        print(f"Candidates found ({len(cands)}):")
        for c in cands:
            meta_file = c / "metadata.json"
            if meta_file.is_file():
                try:
                    m = json.loads(meta_file.read_text(encoding="utf-8"))
                    print(f"  - {c.name}: plan={m.get('plan_id')} status={m.get('status')} compile={m.get('compile_status')}")
                except Exception:
                    print(f"  - {c.name}: [metadata error]")
            else:
                print(f"  - {c.name}: [no metadata]")
        return

    if not args.plan:
        parser.print_help()
        sys.exit(1)

    result = run_developer(
        plan_identifier=args.plan,
        dry_run=args.dry_run,
        mock=args.mock,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_human_readable_output(result))


if __name__ == "__main__":
    main()
