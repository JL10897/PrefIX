#!/usr/bin/env python3
"""
Clean up persona simulation artifacts for a given model.

Rules:
- Determines status per entry using the same thresholds as check_persona_progress.py.
- If an entry is NOT completed:
  * special buckets (log_lines > 3) -> truncate log to first 3 lines.
  * general buckets -> delete the log.
  * in all not-completed cases -> delete the result file.
- Completed entries are left untouched.
- Prints planned actions and asks for confirmation before mutating files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import run_persona_matrix as rpm

# Ensure bfcl_eval is importable when running as a script.
BFCL_ROOT = Path(__file__).resolve().parent.parent
if str(BFCL_ROOT) not in sys.path:
    sys.path.append(str(BFCL_ROOT))
from bfcl_eval.constants.category_mapping import VERSION_PREFIX


HISTORY_ROOT = BFCL_ROOT / "bfcl_eval" / "user_simulator" / "history"
RESULT_ROOT = BFCL_ROOT / "result"


def model_name_from_base_cmd(base_cmd: Sequence[str]) -> str:
    """Extract the model name from the BASE_CMD list."""
    try:
        idx = base_cmd.index("--model")
    except ValueError:
        raise ValueError("BASE_CMD does not contain --model") from None
    try:
        return base_cmd[idx + 1]
    except IndexError:
        raise ValueError("BASE_CMD missing model argument after --model") from None


def model_history_dir(model_name: str) -> str:
    """Match history folder naming (replace hyphens/dots with underscores)."""
    return model_name.replace("-", "_").replace(".", "_")


def variant_label_from_flags(flags: Sequence[str]) -> str:
    """Map flag variant to folder naming convention."""
    flag_set = set(flags)
    return "no_personalization" if "--no-interaction-history" in flag_set else "personalization"


def load_expected_ids(path: Path) -> set[str]:
    """
    Load expected test case IDs from a rewrite file.
    JSON array or JSONL with an "id" field per line.
    """
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    ids: set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, Mapping) and "id" in item:
                ids.add(str(item["id"]))
        if ids:
            return ids
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, Mapping) and "id" in obj:
            ids.add(str(obj["id"]))
    return ids


def read_log_info(path: Path) -> dict:
    """Return metadata about a history log."""
    if not path.exists():
        return {"exists": False, "line_count": 0, "has_end": False}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return {"exists": True, "line_count": 0, "has_end": False}
    line_count = len(lines)
    has_end = False
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if "<END_SIMULATION>" in stripped:
            has_end = True
        break
    return {"exists": True, "line_count": line_count, "has_end": has_end}


def read_result_info(path: Path) -> dict:
    """Return metadata about a result file."""
    if not path.exists():
        return {"exists": False, "nonempty": False, "has_error": False}
    text = path.read_text(encoding="utf-8")
    nonempty = bool(text.strip())
    has_error = False
    try:
        obj = json.loads(text)
        if isinstance(obj, Mapping):
            if obj.get("error"):
                has_error = True
            else:
                for v in obj.values():
                    if isinstance(v, str) and re.search(r"error during inference", v, re.IGNORECASE):
                        has_error = True
                        break
                    if isinstance(v, str) and re.search(r"error code\\s*[:=]\\s*\\d+", v, re.IGNORECASE):
                        has_error = True
                        break
    except Exception:
        pass
    if not has_error:
        if re.search(r"error during inference", text, re.IGNORECASE):
            has_error = True
        elif re.search(r"error code\\s*[:=]\\s*\\d+", text, re.IGNORECASE):
            has_error = True
    return {"exists": True, "nonempty": nonempty, "has_error": has_error}


SPECIAL_PERSONAS = {
    "error_discovery_brief",
    "error_discovery_detail",
    "error_retry_escalation",
    "error_retry_silent",
    "tool_switch_high_agency",
    "tool_switch_low_agency",
}


def classify_bucket(log_lines: int, has_end: bool, has_result: bool, has_error: bool, is_special_persona: bool) -> str:
    """
    Map log/result metadata to a bucket.
    Buckets mirror check_persona_progress thresholds with persona-based special/general.
    """
    if log_lines > 80:
        return "Error Not Rerun"
    if has_error:
        if is_special_persona and log_lines >= 3:
            return "Started but error (special)"
        if not is_special_persona and log_lines > 0:
            return "Started but error (general)"
    if not has_end:
        if is_special_persona and log_lines > 3 and not has_result:
            return "Started but incomplete (special)"
        if (not is_special_persona) and log_lines > 0 and not has_result:
            return "Started but incomplete (general)"
        if is_special_persona and log_lines > 0 and not has_result:
            return "Not yet started (special)"
        if (not is_special_persona) and log_lines == 0 and not has_result:
            return "Not yet started (general)"
    if has_end and has_result:
        if is_special_persona:
            return "Completed (special)"
        return "Completed (general)"
    return "Uncategorized"


def plan_actions_for_entry(entry_id: str, history_dir: Path, result_dir: Path, is_special_persona: bool) -> tuple[str, list[Path], list[tuple[Path, int]]]:
    """
    Return (bucket, logs_to_delete, logs_to_truncate) for a single entry.
    truncate list items are (path, keep_lines).
    """
    log_path = history_dir / f"{entry_id}.json"
    result_path = result_dir / f"{VERSION_PREFIX}_{entry_id}_result.json"
    log_info = read_log_info(log_path)
    result_info = read_result_info(result_path)

    bucket = classify_bucket(
        log_lines=log_info["line_count"],
        has_end=log_info["has_end"],
        has_result=result_info["exists"] and result_info["nonempty"],
        has_error=result_info["has_error"],
        is_special_persona=is_special_persona,
    )

    logs_to_delete: list[Path] = []
    logs_to_truncate: list[tuple[Path, int]] = []

    if bucket not in ("Completed (special)", "Completed (general)", "Error Not Rerun"):
        if is_special_persona:
            if log_info["exists"]:
                logs_to_truncate.append((log_path, 3))
        else:
            if log_info["exists"]:
                logs_to_delete.append(log_path)
        # Always delete result for not-completed buckets
        if result_info["exists"]:
            logs_to_delete.append(result_path)

    return bucket, logs_to_delete, logs_to_truncate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean up persona run artifacts for a model.")
    parser.add_argument(
        "--model",
        required=True,
        help="Model name to check (defaults to model in run_persona_matrix.py).",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)

    model_name = args.model
    history_model_dir = model_history_dir(model_name)

    planned_delete: list[Path] = []
    planned_truncate: list[tuple[Path, int]] = []
    kept_completed_logs: list[Path] = []
    kept_completed_results: list[Path] = []

    for persona in rpm.PERSONAS:
        rewrite_path = rpm.rewrite_path_for_persona(persona)
        expected_ids = load_expected_ids(rewrite_path) if rewrite_path.exists() else set()

        for flags in rpm.FLAG_VARIANTS:
            variant_label = variant_label_from_flags(flags)
            persona_suffix = rpm.persona_to_suffix(persona)

            history_dir = HISTORY_ROOT / history_model_dir / variant_label / persona_suffix
            result_dir = RESULT_ROOT / model_name / variant_label / persona_suffix

            # Collect IDs from expected, logs, and results
            log_ids = {p.stem for p in history_dir.glob("*.json")} if history_dir.exists() else set()
            result_ids = {
                p.stem.replace(f"{VERSION_PREFIX}_", "").replace("_result", "")
                for p in result_dir.glob(f"{VERSION_PREFIX}_*_result.json")
            } if result_dir.exists() else set()
            ids = expected_ids or set()
            ids = ids | log_ids | result_ids
            if not ids:
                continue

            for entry_id in ids:
                bucket, to_delete, to_truncate = plan_actions_for_entry(
                    entry_id,
                    history_dir,
                    result_dir,
                    is_special_persona=persona_suffix in SPECIAL_PERSONAS,
                )
                if bucket not in ("Completed (special)", "Completed (general)", "Error Not Rerun"):
                    planned_delete.extend(to_delete)
                    planned_truncate.extend(to_truncate)
                else:
                    log_path = history_dir / f"{entry_id}.json"
                    result_path = result_dir / f"{VERSION_PREFIX}_{entry_id}_result.json"
                    if log_path.exists():
                        kept_completed_logs.append(log_path)
                    if result_path.exists():
                        kept_completed_results.append(result_path)

    # Deduplicate while preserving order
    seen = set()
    unique_delete = []
    for p in planned_delete:
        if p not in seen:
            seen.add(p)
            unique_delete.append(p)
    seen_trunc = set()
    unique_truncate = []
    for p, k in planned_truncate:
        if (p, k) not in seen_trunc:
            seen_trunc.add((p, k))
            unique_truncate.append((p, k))

    if not unique_delete and not unique_truncate:
        print("Nothing to clean.")
        return 0
    dirs_to_remove: set[Path] = set()

    print("Planned truncations (keep first N lines):")
    if unique_truncate:
        dir_map = {}
        for p, k in unique_truncate:
            dir_map.setdefault(p.parent, []).append((p, k))
        for d in sorted(dir_map.keys()):
            print(f"- {d}:")
            for p, k in dir_map[d]:
                print(f"    {p.name} (keep {k} lines)")
    else:
        print("- None")
    print("\nWill keep completed logs/results:")
    if kept_completed_logs or kept_completed_results:
        dir_map_keep = {}
        for p in kept_completed_logs + kept_completed_results:
            dir_map_keep.setdefault(p.parent, []).append(p.name)
        for d in sorted(dir_map_keep.keys()):
            print(f"- {d}:")
            for name in sorted(dir_map_keep[d]):
                print(f"    {name}")
    else:
        print("- None")

    confirm = input("\nProceed with these changes? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return 0

    for p, k in unique_truncate:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
            p.write_text("\n".join(lines[:k]), encoding="utf-8")
        except FileNotFoundError:
            continue

    for p in unique_delete:
        try:
            p.unlink()
        except FileNotFoundError:
            continue
        dirs_to_remove.add(p.parent)
    for p, _ in unique_truncate:
        dirs_to_remove.add(p.parent)

    # Remove empty directories (parents up to model folder)
    for d in sorted(dirs_to_remove, key=lambda x: len(str(x)), reverse=True):
        try:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        except OSError:
            continue

    # Final pass: remove empty persona folders under model/no_personalization|personalization
    for variant_dir in [
        RESULT_ROOT / model_name / "personalization",
        RESULT_ROOT / model_name / "no_personalization",
        HISTORY_ROOT / history_model_dir / "personalization",
        HISTORY_ROOT / history_model_dir / "no_personalization",
    ]:
        if not variant_dir.exists():
            continue
        for persona_dir in variant_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            try:
                if not any(persona_dir.iterdir()):
                    persona_dir.rmdir()
            except OSError:
                continue

    print("Cleanup completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
