#!/usr/bin/env python3
"""
Scan persona simulation outputs to see which runs completed.

Rules:
- Uses the personas/flag variants from run_persona_matrix.py.
- A run is "complete" when the last non-empty line in the history log
  contains the token <END_SIMULATION>.
- Expected IDs come from the rewrite file in the Processing directory.
- Reports, for both personalization and no_personalization variants,
  which personas have fully finished vs. which are missing or incomplete.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
import re

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


def load_expected_ids(path: Path) -> set[str]:
    """
    Load expected test case IDs from a rewrite file.

    Files are JSONL where each line is an object that includes an "id" field.
    If the file is a JSON array, fall back to that format as well.
    """
    if not path.exists():
        return set()

    text = path.read_text(encoding="utf-8")

    # Try JSON array first.
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

    # Fallback: JSONL.
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


def last_line_has_end_marker(path: Path) -> bool:
    """Check whether the last non-empty line contains the end token."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return False

    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        return "<END_SIMULATION>" in stripped
    return False


@dataclass
class RunStatus:
    persona: str
    variant_label: str
    expected_ids: set[str]
    completed_ids: set[str]
    incomplete_ids: set[str]
    incomplete_logs: list[str]
    missing_ids: set[str]
    extra_ids: set[str]
    history_dir: Path
    history_dir_exists: bool
    result_dir: Path
    result_dir_exists: bool
    rewrite_exists: bool


def collect_status_for_persona(
    persona: str,
    variant_label: str,
    expected_ids: set[str],
    history_dir: Path,
    result_dir: Path,
    rewrite_exists: bool,
) -> RunStatus:
    completed_ids: set[str] = set()
    incomplete_ids: set[str] = set()
    incomplete_logs: list[str] = []

    if history_dir.exists():
        for log_file in history_dir.glob("*.json"):
            test_id = log_file.stem
            if last_line_has_end_marker(log_file):
                completed_ids.add(test_id)
            else:
                incomplete_ids.add(test_id)
                incomplete_logs.append(str(log_file))

    # Missing = expected but neither completed nor incomplete (i.e., no log found/empty)
    missing_ids = expected_ids - completed_ids - incomplete_ids
    extra_ids = completed_ids - expected_ids

    return RunStatus(
        persona=persona,
        variant_label=variant_label,
        expected_ids=expected_ids,
        completed_ids=completed_ids,
        incomplete_ids=incomplete_ids,
        incomplete_logs=incomplete_logs,
        missing_ids=missing_ids,
        extra_ids=extra_ids,
        history_dir=history_dir,
        history_dir_exists=history_dir.exists(),
        result_dir=result_dir,
        result_dir_exists=result_dir.exists(),
        rewrite_exists=rewrite_exists,
    )


def variant_label_from_flags(flags: Sequence[str]) -> str:
    """Map flag variant to folder naming convention."""
    flag_set = set(flags)
    return "no_personalization" if "--no-interaction-history" in flag_set else "personalization"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report which persona runs finished (<END_SIMULATION> in history logs)."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name to check (defaults to model in run_persona_matrix.py).",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Show full ID lists instead of truncated previews.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the report as a text file. If omitted, defaults to file_status_<model>.txt alongside this script.",
    )
    return parser


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
    # Prefer structured JSON detection
    try:
        obj = json.loads(text)
        if isinstance(obj, Mapping):
            if obj.get("error"):
                has_error = True
            else:
                # Look for error-like strings in values
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
        # Fallback to textual heuristics
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


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)

    model_name = args.model or model_name_from_base_cmd(rpm.BASE_CMD)
    history_model_dir = model_history_dir(model_name)

    def resolve_result_dir(
        base_model_name: str, variant_label: str, persona_suffix: str
    ) -> Path:
        """
        Result folders sometimes use hyphens while callers pass underscores.
        Prefer the exact model_name, but fall back to common alternates so
        completed runs aren't misclassified as missing results.
        """
        candidates = [
            base_model_name,
            base_model_name.replace("_", "-"),
            base_model_name.replace("-", "_"),
        ]
        seen = set()
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            path = RESULT_ROOT / name / variant_label / persona_suffix
            if path.exists():
                return path
        # Default to the first (original) even if missing, so we still report status.
        return RESULT_ROOT / base_model_name / variant_label / persona_suffix

    header = [
        f"Model: {model_name}",
        f"History root: {HISTORY_ROOT / history_model_dir}",
        f"Result root: {RESULT_ROOT / model_name}",
        f"Processing dir: {rpm.PROCESSING_DIR}",
        f"Test category: {rpm.TEST_CATEGORY}",
    ]
    output_lines: list[str] = []
    output_lines.extend(header)
    output_lines.append("=" * 60)
    output_lines.append("")

    statuses: list[RunStatus] = []

    for persona in rpm.PERSONAS:
        rewrite_path = rpm.rewrite_path_for_persona(persona)
        rewrite_exists = rewrite_path.exists()
        expected_ids = load_expected_ids(rewrite_path) if rewrite_exists else set()

        for flags in rpm.FLAG_VARIANTS:
            variant_label = variant_label_from_flags(flags)
            persona_suffix = rpm.persona_to_suffix(persona)

            history_dir = (
                HISTORY_ROOT / history_model_dir / variant_label / persona_suffix
            )
            result_dir = resolve_result_dir(model_name, variant_label, persona_suffix)

            status = collect_status_for_persona(
                persona=persona,
                variant_label=variant_label,
                expected_ids=expected_ids,
                history_dir=history_dir,
                result_dir=result_dir,
                rewrite_exists=rewrite_exists,
            )
            statuses.append(status)

    def classify_entry(entry_id: str, status: RunStatus, is_special_persona: bool) -> tuple[str, str]:
        """
        Classify a single entry for a given persona/variant.

        Returns (bucket_label, detail_string).
        """
        log_path = status.history_dir / f"{entry_id}.json"
        result_path = status.result_dir / f"{VERSION_PREFIX}_{entry_id}_result.json"
        log_info = read_log_info(log_path)
        result_info = read_result_info(result_path)

        log_lines = log_info["line_count"]
        has_end = log_info["has_end"]
        has_result = result_info["exists"] and result_info["nonempty"]
        has_error = result_info["has_error"]

        # If the run ended cleanly, count it as completed even if the log is long.
        if has_end and has_result:
            if is_special_persona:
                return ("Completed (special)", f"{entry_id}")
            return ("Completed (general)", f"{entry_id}")

        # Hard bucket: overly long logs without a clean end are treated as a non-rerun error.
        if log_lines > 180:
            return ("Error Not Rerun", f"{entry_id} (log_lines={log_lines})")

        # Special vs general determined by persona type, not line counts beyond the above.
        if has_error:
            if is_special_persona and log_lines >= 3:
                return ("Started but error (special)", f"{entry_id} (log_lines={log_lines}, error in result)")
            if not is_special_persona and log_lines > 0:
                return ("Started but error (general)", f"{entry_id} (log_lines={log_lines}, error in result)")

        if not has_end:
            if is_special_persona and log_lines > 3 and not has_result:
                return ("Started but incomplete (special)", f"{entry_id} (log_lines={log_lines}, no <END_SIMULATION>, no result)")
            if (not is_special_persona) and log_lines > 0 and not has_result:
                return ("Started but incomplete (general)", f"{entry_id} (log_lines={log_lines}, no <END_SIMULATION>, no result)")
            if is_special_persona and log_lines > 0 and not has_result:
                return ("Not yet started (special)", f"{entry_id} (log_lines={log_lines}, no result)")
            if (not is_special_persona) and log_lines == 0 and not has_result:
                return ("Not yet started (general)", f"{entry_id} (no log, no result)")

        # Fallback bucket
        return ("Uncategorized", f"{entry_id} (log_lines={log_lines}, has_end={has_end}, has_result={has_result}, has_error={has_error})")

    # Group output by personalization variant.
    variant_sections: dict[str, dict[str, list[str]]] = {}
    fully_finished_settings: list[str] = []
    finished_pass_settings: list[str] = []
    missing_end_by_variant: dict[str, dict[str, list[tuple[str, int]]]] = {}

    for status in statuses:
        # Collect all IDs to consider: expected ids plus any found in logs/results.
        log_ids = {p.stem for p in status.history_dir.glob("*.json")} if status.history_dir_exists else set()
        result_ids = {
            p.stem.replace(f"{VERSION_PREFIX}_", "").replace("_result", "")
            for p in status.result_dir.glob(f"{VERSION_PREFIX}_*_result.json")
        } if status.result_dir_exists else set()
        ids = status.expected_ids or set()
        ids = ids | log_ids | result_ids
        if not ids:
            continue

        buckets: dict[str, list[str]] = {
            "Started but error (special)": [],
            "Started but error (general)": [],
            "Started but incomplete (special)": [],
            "Started but incomplete (general)": [],
            "Not yet started (special)": [],
            "Not yet started (general)": [],
            "Completed (special)": [],
            "Completed (general)": [],
            "Error Not Rerun": [],
            "Uncategorized": [],
        }

        is_special_persona = rpm.persona_to_suffix(status.persona) in SPECIAL_PERSONAS

        for entry_id in sorted(ids):
            log_path = status.history_dir / f"{entry_id}.json"
            log_info = read_log_info(log_path)
            if not log_info["has_end"]:
                missing_end_by_variant.setdefault(status.variant_label, {}).setdefault(
                    status.persona, []
                ).append((entry_id, log_info["line_count"]))
            bucket, detail = classify_entry(entry_id, status, is_special_persona)
            if "log_lines=" not in detail:
                detail = f"{detail} (log_lines={log_info['line_count']})"
            buckets.setdefault(bucket, []).append(detail)

        variant_sections.setdefault(status.variant_label, {})
        variant_sections[status.variant_label][status.persona] = []
        for bucket_name, entries in buckets.items():
            if not entries:
                continue
            variant_sections[status.variant_label][status.persona].append(
                f"{bucket_name}:"
            )
            for item in entries:
                variant_sections[status.variant_label][status.persona].append(f"    - {item}")

        # Determine if this setting is fully finished (all ids completed).
        completed_ids = set()
        for k in ("Completed (special)", "Completed (general)"):
            completed_ids.update({item.split()[0] for item in buckets.get(k, [])})
        if ids and completed_ids == ids:
            fully_finished_settings.append(f"{status.variant_label}/{status.persona}")

        finished_pass_ids = set(completed_ids)
        finished_pass_ids.update({item.split()[0] for item in buckets.get("Error Not Rerun", [])})
        if ids and finished_pass_ids == ids:
            finished_pass_settings.append(f"{status.variant_label}/{status.persona}")

    for variant in sorted(variant_sections.keys()):
        output_lines.append(f"== {variant} ==")
        personas = variant_sections[variant]
        if not personas:
            output_lines.append("- None")
            output_lines.append("")
            continue
        for persona, lines_for_persona in personas.items():
            output_lines.append(f"- {persona}:")
            if lines_for_persona:
                for line in lines_for_persona:
                    output_lines.append(f"  {line}")
            else:
                output_lines.append("  (no entries found)")
        output_lines.append("")

    output_lines.append("Not completed due to missing <END_SIMULATION> (by variant):")
    if missing_end_by_variant:
        for variant in sorted(missing_end_by_variant.keys()):
            personas = missing_end_by_variant[variant]
            flat_entries: list[str] = []
            for persona, entries in personas.items():
                for entry_id, line_count in entries:
                    flat_entries.append(f"{persona}/{entry_id}")
            output_lines.append(f"- {variant}: {len(flat_entries)} entries")
            for persona, entries in sorted(personas.items()):
                ids_text = ", ".join(
                    f"{entry_id} (log_lines={line_count})"
                    for entry_id, line_count in sorted(entries, key=lambda x: x[0])
                )
                output_lines.append(f"    - {persona}: {ids_text}")
    else:
        output_lines.append("- none")
    output_lines.append("")

    if fully_finished_settings:
        output_lines.append("Fully finished settings (all entries completed):")
        output_lines.extend(f"- {s}" for s in sorted(fully_finished_settings))
    else:
        output_lines.append("Fully finished settings: none")

    if finished_pass_settings:
        output_lines.append(
            f"\nFinished-pass settings (completed or Error Not Rerun only): {len(finished_pass_settings)}"
        )
        output_lines.extend(f"- {s}" for s in sorted(finished_pass_settings))
    else:
        output_lines.append("\nFinished-pass settings: none")

    report_text = "\n".join(output_lines)
    print(report_text)

    output_path = args.output
    if not output_path:
        safe_model = model_name.replace("/", "_").replace(" ", "_")
        output_path = Path(__file__).parent / f"file_status_{safe_model}.txt"
    Path(output_path).write_text(report_text, encoding="utf-8")
    print(f"\nReport saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
