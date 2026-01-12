#!/usr/bin/env python3
"""
Clean up empty history logs and report incomplete runs.

Behaviors:
- Target the history directory for a given model (defaults to model in run_persona_matrix.py).
- Optionally narrow to a specific variant (personalization/no_personalization) and/or persona.
- Remove history log files whose contents are entirely empty/whitespace.
- After removals, delete any now-empty persona folders; if a variant folder becomes empty, delete it too.
- Report which remaining logs are started but not finished (i.e., do not end with <END_SIMULATION>).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Sequence

import run_persona_matrix as rpm


BFCL_ROOT = Path(__file__).resolve().parent.parent
HISTORY_ROOT = BFCL_ROOT / "bfcl_eval" / "user_simulator" / "history"
RESULT_ROOT = BFCL_ROOT / "result"


def model_name_from_base_cmd(base_cmd: Sequence[str]) -> str:
    try:
        idx = base_cmd.index("--model")
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError("BASE_CMD does not contain --model") from exc
    try:
        return base_cmd[idx + 1]
    except IndexError as exc:  # pragma: no cover - defensive
        raise ValueError("BASE_CMD missing model argument after --model") from exc


def model_history_dir(model_name: str) -> str:
    return model_name.replace("-", "_").replace(".", "_")


def last_line_has_end_marker(path: Path) -> bool:
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


def is_empty_file(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    return content.strip() == ""


def line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except UnicodeDecodeError:
        return 0


def clean_history(
    model_name: str,
    variants: list[str],
    personas: set[str] | None,
    delete_incomplete: bool,
) -> dict[str, list[str]]:
    model_dir = model_history_dir(model_name)
    base = HISTORY_ROOT / model_dir
    result_base = RESULT_ROOT / model_name

    special_personas = {
        "error_discovery_brief",
        "error_discovery_detail",
        "tool_switch_high_agency",
        "tool_switch_low_agency",
        "error_retry_escalation",
        "error_retry_silent",
    }

    deleted_files: list[str] = []
    deleted_result_files: list[str] = []
    deleted_incomplete_files: list[str] = []
    deleted_incomplete_result_files: list[str] = []
    deleted_dirs: list[str] = []
    incomplete: list[str] = []

    if not base.exists():
        sys.stdout.write(f"History root not found: {base}\n")
        return {
            "deleted_files": deleted_files,
            "deleted_result_files": deleted_result_files,
            "deleted_dirs": deleted_dirs,
            "incomplete": incomplete,
        }

    for variant in variants:
        variant_dir = base / variant
        if not variant_dir.exists():
            continue

        persona_dirs = (
            [variant_dir / p for p in personas]
            if personas
            else [p for p in variant_dir.iterdir() if p.is_dir()]
        )

        for p_dir in persona_dirs:
            if not p_dir.exists():
                continue
            persona_name = p_dir.name
            result_dir = result_base / variant / persona_name
            is_special = persona_name in special_personas

            for log_file in p_dir.glob("*.json"):
                if is_special:
                    # Special personas: mark incomplete if >3 lines and no END; optionally delete.
                    started = line_count(log_file) > 3
                    finished = last_line_has_end_marker(log_file)
                    if started and not finished:
                        if delete_incomplete:
                            log_file.unlink()
                            deleted_incomplete_files.append(str(log_file))
                            if result_dir.exists():
                                for candidate in result_dir.glob(f"{log_file.stem}.*"):
                                    try:
                                        candidate.unlink()
                                        deleted_incomplete_result_files.append(str(candidate))
                                    except OSError:
                                        pass
                        else:
                            incomplete.append(str(log_file))
                    continue

                if is_empty_file(log_file):
                    log_file.unlink()
                    deleted_files.append(str(log_file))

                    # Remove result files with matching stem under same persona/variant.
                    if result_dir.exists():
                        for candidate in result_dir.glob(f"{log_file.stem}.*"):
                            try:
                                candidate.unlink()
                                deleted_result_files.append(str(candidate))
                            except OSError:
                                pass
                    continue

                started = True  # non-empty file
                finished = last_line_has_end_marker(log_file)
                if started and not finished:
                    if delete_incomplete:
                        try:
                            log_file.unlink()
                            deleted_incomplete_files.append(str(log_file))
                        except OSError:
                            pass
                        if result_dir.exists():
                            for candidate in result_dir.glob(f"{log_file.stem}.*"):
                                try:
                                    candidate.unlink()
                                    deleted_incomplete_result_files.append(str(candidate))
                                except OSError:
                                    pass
                    else:
                        incomplete.append(str(log_file))

            if not is_special:
                # remove persona dir if empty
                try:
                    p_dir.rmdir()
                    deleted_dirs.append(str(p_dir))
                except OSError:
                    pass

                # if persona result dir exists and is now empty, remove it
                if result_dir.exists():
                    try:
                        result_dir.rmdir()
                        deleted_dirs.append(str(result_dir))
                    except OSError:
                        pass

        # remove variant dir if empty
        try:
            variant_dir.rmdir()
            deleted_dirs.append(str(variant_dir))
        except OSError:
            pass
        # remove result variant dir if empty
        result_variant_dir = result_base / variant
        if result_variant_dir.exists():
            try:
                result_variant_dir.rmdir()
                deleted_dirs.append(str(result_variant_dir))
            except OSError:
                pass

    return {
            "deleted_files": deleted_files,
            "deleted_result_files": deleted_result_files,
            "deleted_incomplete_files": deleted_incomplete_files,
            "deleted_incomplete_result_files": deleted_incomplete_result_files,
            "deleted_dirs": deleted_dirs,
            "incomplete": incomplete,
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove empty history logs and list started-but-not-finished logs."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name to clean (defaults to model in run_persona_matrix.py).",
    )
    parser.add_argument(
        "--variant",
        choices=["personalization", "no_personalization", "all"],
        default="all",
        help="History variant to clean; default is all.",
    )
    parser.add_argument(
        "--personas",
        default=None,
        help="Comma-separated personas to clean (default: all personas under the variant).",
    )
    parser.add_argument(
        "--delete-incomplete",
        action="store_true",
        help="If set, delete logs that started but did not finish (<END_SIMULATION> missing). Requires --model.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)

    if args.delete_incomplete and not args.model:
        raise SystemExit("When using --delete-incomplete, please specify --model explicitly.")

    model_name = args.model or model_name_from_base_cmd(rpm.BASE_CMD)
    if args.variant == "all":
        variants = ["personalization", "no_personalization"]
    else:
        variants = [args.variant]

    personas = None
    if args.personas:
        personas = {rpm.persona_to_suffix(p.strip()) for p in args.personas.split(",") if p.strip()}

    summary = clean_history(
        model_name=model_name,
        variants=variants,
        personas=personas,
        delete_incomplete=args.delete_incomplete,
    )

    sys.stdout.write(f"Model: {model_name}\n")
    sys.stdout.write(f"Variants: {', '.join(variants)}\n")
    if personas:
        sys.stdout.write(f"Personas: {', '.join(sorted(personas))}\n")
    sys.stdout.write("\n")

    sys.stdout.write("Deleted empty files:\n")
    if summary["deleted_files"]:
        for path in summary["deleted_files"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    sys.stdout.write("\nDeleted result files (matching empty logs):\n")
    if summary["deleted_result_files"]:
        for path in summary["deleted_result_files"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    sys.stdout.write("\nDeleted empty dirs:\n")
    if summary["deleted_dirs"]:
        for path in summary["deleted_dirs"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    sys.stdout.write("\nDeleted started-but-not-finished logs:\n")
    if summary["deleted_incomplete_files"]:
        for path in summary["deleted_incomplete_files"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    sys.stdout.write("\nDeleted result files (matching deleted incomplete logs):\n")
    if summary["deleted_incomplete_result_files"]:
        for path in summary["deleted_incomplete_result_files"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    sys.stdout.write("\nStarted but not finished (no <END_SIMULATION>):\n")
    if summary["incomplete"]:
        for path in summary["incomplete"]:
            sys.stdout.write(f"- {path}\n")
    else:
        sys.stdout.write("- None\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
