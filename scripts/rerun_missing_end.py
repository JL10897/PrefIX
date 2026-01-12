#!/usr/bin/env python3
"""
Rerun helper for entries missing completion markers or flagged as Error Not Rerun.

- Parses file_status_<model>.txt emitted by check_persona_progress.py.
- Supports two modes: missing_end (default) or error_not_rerun.
- Prints the planned tasks and asks for confirmation before running unless --yes is supplied.
- Uses BaseHandlerRerun to append history, relax line cap to 120, and write rerun results safely.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
import re

from bfcl_eval._llm_response_generation import (
    build_handler,
    get_involved_test_entries,
    process_multi_turn_test_case,
)
from bfcl_eval.constants.category_mapping import VERSION_PREFIX
from bfcl_eval.constants.eval_config import RESULT_PATH
from bfcl_eval.model_handler.base_handler_rerun import enable_rerun_mode
import run_persona_matrix as rpm


BFCL_ROOT = Path(__file__).resolve().parent.parent
HISTORY_ROOT = BFCL_ROOT / "bfcl_eval" / "user_simulator" / "history"
RESULT_ROOT = BFCL_ROOT / "result"


@dataclass
class RerunTask:
    variant_label: str  # personalization | no_personalization
    persona: str
    persona_suffix: str
    entry_id: str
    log_lines: int | None
    history_path: Path
    result_path: Path


def model_history_dir(model_name: str) -> str:
    return model_name.replace("-", "_").replace(".", "_")


def parse_missing_end_section(text: str) -> list[dict[str, str | int | None]]:
    """
    Extract entries from the 'Not completed due to missing <END_SIMULATION>' block.
    """
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if "Not completed due to missing <END_SIMULATION>" in line:
            start = idx + 1
            break
    if start is None:
        return []

    entries: list[dict[str, str | int | None]] = []
    variant = None

    def parse_entry(token: str) -> tuple[str, int | None]:
        m = re.match(r"(?P<id>[^()\\s]+)\\s*(?:\\(log_lines=(?P<lines>\\d+)\\))?", token.strip())
        if not m:
            return token.strip(), None
        entry_id = m.group("id")
        log_lines = m.group("lines")
        return entry_id, int(log_lines) if log_lines else None

    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("Fully finished settings") or stripped.startswith("Finished-pass settings"):
            break
        if not stripped:
            continue
        variant_match = re.match(r"-\\s+(?P<variant>\\w+):", stripped)
        if variant_match:
            variant = variant_match.group("variant")
            continue
        persona_match = re.match(r"-\\s+(?P<persona>[\\w_]+):\\s*(?P<rest>.*)", stripped)
        if persona_match and variant:
            persona = persona_match.group("persona")
            rest = persona_match.group("rest")
            tokens = [t.strip() for t in rest.split(",") if t.strip()]
            for token in tokens:
                entry_id, log_lines = parse_entry(token)
                entries.append(
                    {
                        "variant_label": variant,
                        "persona": persona,
                        "entry_id": entry_id,
                        "log_lines": log_lines,
                    }
                )
    return entries


def parse_error_not_rerun(text: str) -> list[dict[str, str | int | None]]:
    """
    Parse the per-variant sections and collect entries under 'Error Not Rerun:' buckets.
    """
    entries: list[dict[str, str | int | None]] = []
    current_variant = None
    current_persona = None
    capture_error = False

    for raw_line in text.splitlines():
        if not raw_line:
            continue
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("==") and stripped.endswith("=="):
            # e.g., "== personalization =="
            current_variant = stripped.strip("=").strip()
            current_persona = None
            capture_error = False
            continue

        if stripped.startswith("- ") and stripped.endswith(":"):
            # Persona header, reset bucket capture
            current_persona = stripped[2:-1]
            capture_error = False
            continue

        if stripped.endswith(":"):
            capture_error = stripped == "Error Not Rerun:"
            continue

        if capture_error and stripped.startswith("- "):
            token = stripped[2:]
            m = re.match(r"(?P<id>[^()\\s]+)\\s*(?:\\(log_lines=(?P<lines>\\d+)\\))?", token)
            entry_id = m.group("id") if m else token.strip()
            log_lines = int(m.group("lines")) if m and m.group("lines") else None
            if current_variant and current_persona:
                entries.append(
                    {
                        "variant_label": current_variant,
                        "persona": current_persona,
                        "entry_id": entry_id,
                        "log_lines": log_lines,
                    }
                )
    return entries


def variant_to_flags(variant_label: str) -> list[str]:
    if variant_label == "no_personalization":
        return ["--no-interaction-history"]
    return []


def build_tasks(model_name: str, missing_entries: list[Mapping[str, str | int | None]]) -> list[RerunTask]:
    history_dir_name = model_history_dir(model_name)
    tasks: list[RerunTask] = []
    for entry in missing_entries:
        variant_label = str(entry["variant_label"])
        persona = str(entry["persona"])
        entry_id = str(entry["entry_id"])
        log_lines_raw = entry.get("log_lines")
        log_lines = int(log_lines_raw) if isinstance(log_lines_raw, int) else None

        persona_suffix = rpm.persona_to_suffix(persona)
        history_path = (
            HISTORY_ROOT
            / history_dir_name
            / variant_label
            / persona_suffix
            / f"multi_turn_long_context_{entry_id}.json"
        )
        result_path = (
            RESULT_ROOT
            / model_name
            / variant_label
            / persona_suffix
            / f"{VERSION_PREFIX}_{entry_id}_result.json"
        )
        tasks.append(
            RerunTask(
                variant_label=variant_label,
                persona=persona,
                persona_suffix=persona_suffix,
                entry_id=entry_id,
                log_lines=log_lines,
                history_path=history_path,
                result_path=result_path,
            )
        )
    return tasks


def summarize_tasks(tasks: list[RerunTask]) -> str:
    lines: list[str] = []
    lines.append(f"Total tasks: {len(tasks)}")
    grouped: dict[str, list[RerunTask]] = defaultdict(list)
    for t in tasks:
        key = f"{t.variant_label}/{t.persona}"
        grouped[key].append(t)
    for key in sorted(grouped.keys()):
        entries = grouped[key]
        ids = ", ".join(f"{t.entry_id} (log_lines={t.log_lines})" for t in entries)
        lines.append(f"- {key}: {ids}")
    return "\n".join(lines)


def load_entries_for_persona(persona_suffix: str, include_history: bool) -> list[dict]:
    _, _, entries = get_involved_test_entries(
        [rpm.TEST_CATEGORY],
        run_ids=False,
        persona_suffix=persona_suffix,
    )
    processed = process_multi_turn_test_case(entries)
    return processed


def execute_tasks(
    tasks: list[RerunTask],
    model_name: str,
    *,
    overwrite_canonical: bool = False,
) -> None:
    successes: list[str] = []
    failures: list[str] = []

    # group by (variant, persona) to reuse handler and loaded entries
    grouped: dict[tuple[str, str], list[RerunTask]] = defaultdict(list)
    for task in tasks:
        grouped[(task.variant_label, task.persona)].append(task)

    for (variant_label, persona), persona_tasks in grouped.items():
        include_history = variant_label != "no_personalization"
        persona_suffix = rpm.persona_to_suffix(persona)
        entries = load_entries_for_persona(persona_suffix, include_history)
        entry_index = {entry["id"]: entry for entry in entries}

        handler = build_handler(
            model_name,
            temperature=0,
            simulator_persona=persona,
            include_interaction_history=include_history,
            interaction_history_suffix=persona_suffix,
        )
        enable_rerun_mode(
            handler,
            history_line_limit=160,
            overwrite_canonical=overwrite_canonical,
            result_suffix="_rerun",
        )

        for task in persona_tasks:
            entry = entry_index.get(task.entry_id)
            if not entry:
                failures.append(f"{variant_label}/{persona}/{task.entry_id} (missing entry in rewrite)")
                continue
            try:
                result, _ = handler.inference(
                    deepcopy(entry),
                    include_input_log=False,
                    exclude_state_log=False,
                )
                handler.write(result, result_dir=RESULT_PATH, update_mode=False)
                successes.append(f"{variant_label}/{persona}/{task.entry_id}")
            except Exception as exc:  # pragma: no cover - runtime protection
                failures.append(f"{variant_label}/{persona}/{task.entry_id}: {exc}")

    print("\nRerun complete.")
    print(f"Successes: {len(successes)}")
    for item in successes:
        print(f"  - {item}")
    if failures:
        print(f"Failures: {len(failures)}")
        for item in failures:
            print(f"  - {item}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="List and optionally rerun entries missing <END_SIMULATION> or marked Error Not Rerun."
    )
    parser.add_argument("--model", default=None, help="Model name; defaults to model in run_persona_matrix.py BASE_CMD.")
    parser.add_argument(
        "--status-file",
        default=None,
        help="Path to file_status_<model>.txt. Defaults to scripts/file_status_<model>.txt",
    )
    parser.add_argument(
        "--mode",
        choices=["missing_end", "error_not_rerun"],
        default="missing_end",
        help="Which bucket to rerun.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip interactive confirmation.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute reruns. Without this flag, the script only lists planned tasks.",
    )
    parser.add_argument(
        "--overwrite-canonical",
        action="store_true",
        help="Backup then overwrite canonical result file instead of writing _rerun suffix.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    model_name = args.model or rpm.BASE_CMD[rpm.BASE_CMD.index("--model") + 1]
    safe_model = model_name.replace("/", "_").replace(" ", "_")
    status_file = (
        Path(args.status_file)
        if args.status_file
        else Path(__file__).parent / f"file_status_{safe_model}.txt"
    )
    if not status_file.exists():
        print(f"Status file not found: {status_file}", file=sys.stderr)
        return 1

    text = status_file.read_text(encoding="utf-8")
    if args.mode == "missing_end":
        missing_entries = parse_missing_end_section(text)
    else:
        missing_entries = parse_error_not_rerun(text)

    tasks = build_tasks(model_name, missing_entries)

    if not tasks:
        print("No tasks found for the selected mode.")
        return 0

    summary = summarize_tasks(tasks)
    print("Planned rerun tasks:\n")
    print(summary)
    print("\nProceed with rerun?")
    if not args.yes:
        answer = input("Continue? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted by user.")
            return 0
    else:
        print("--yes provided; skipping prompt.")

    if not args.execute:
        print("Execution not requested (use --execute to run).")
        return 0

    execute_tasks(
        tasks,
        model_name=model_name,
        overwrite_canonical=args.overwrite_canonical,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
