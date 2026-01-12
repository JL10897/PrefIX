#!/usr/bin/env python3
"""
Clean up artifacts for entries missing <END_SIMULATION> (or Error Not Rerun).

- Parses file_status_<model>.txt emitted by check_persona_progress.py.
- Lists absolute paths to delete (history, result variants, judge scores) per entry.
- Requires interactive confirmation; --execute performs deletion, otherwise preview only.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping
import re
from typing import List

# Resolve into bfcl repo
SCRIPT_ROOT = Path(__file__).resolve().parent
BFCL_ROOT = SCRIPT_ROOT.parent / "gorilla" / "berkeley-function-call-leaderboard"
sys.path.append(str(BFCL_ROOT))
sys.path.append(str(BFCL_ROOT / "scripts"))

from bfcl_eval.constants.category_mapping import VERSION_PREFIX
import run_persona_matrix as rpm

HISTORY_ROOT = BFCL_ROOT / "bfcl_eval" / "user_simulator" / "history"
RESULT_ROOT = BFCL_ROOT / "result"
JUDGE_ROOT = BFCL_ROOT / "LLM_as_judge_score"


@dataclass
class EntryRef:
    variant_label: str  # personalization | no_personalization
    persona: str
    persona_suffix: str
    entry_id: str


def model_history_dir(model_name: str) -> str:
    return model_name.replace("-", "_").replace(".", "_")


def model_name_variants(model_name: str) -> list[str]:
    variants = [
        model_name,
        model_name.replace("-", "_"),
        model_name.replace("_", "-"),
        model_name.replace(".", "_"),
    ]
    seen = set()
    uniq = []
    for v in variants:
        if v in seen:
            continue
        seen.add(v)
        uniq.append(v)
    return uniq


def parse_missing_end_section(text: str) -> list[EntryRef]:
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

    entries: list[EntryRef] = []
    variant = None

    def parse_entry(token: str) -> str:
        m = re.match(r"(?P<id>[^()\s]+)", token.strip())
        return m.group("id") if m else token.strip()

    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("Fully finished settings") or stripped.startswith("Finished-pass settings"):
            break
        if not stripped:
            continue
        variant_match = re.match(r"-\s+(?P<variant>\w+):", stripped)
        if variant_match:
            variant = variant_match.group("variant")
            continue
        persona_match = re.match(r"-\s+(?P<persona>[^:]+):\s*(?P<rest>.*)", stripped)
        if persona_match and variant:
            persona = persona_match.group("persona").strip()
            rest = persona_match.group("rest")
            tokens = [t.strip() for t in rest.split(",") if t.strip()]
            for token in tokens:
                entry_id = parse_entry(token)
                entries.append(
                    EntryRef(
                        variant_label=variant,
                        persona=persona,
                        persona_suffix=rpm.persona_to_suffix(persona),
                        entry_id=entry_id,
                    )
                )
    return entries


def parse_error_not_rerun(text: str) -> list[EntryRef]:
    """
    Parse the per-variant sections and collect entries under 'Error Not Rerun:' buckets.
    """
    entries: list[EntryRef] = []
    current_variant = None
    current_persona = None
    capture_error = False

    for raw_line in text.splitlines():
        if not raw_line:
            continue
        stripped = raw_line.strip()

        if stripped.startswith("==") and stripped.endswith("=="):
            current_variant = stripped.strip("=").strip()
            current_persona = None
            capture_error = False
            continue

        if stripped.startswith("- ") and stripped.endswith(":"):
            current_persona = stripped[2:-1].strip()
            capture_error = False
            continue

        if stripped.endswith(":"):
            capture_error = stripped == "Error Not Rerun:"
            continue

        if capture_error and stripped.startswith("- "):
            token = stripped[2:]
            m = re.match(r"(?P<id>[^()\s]+)", token)
            entry_id = m.group("id") if m else token.strip()
            if current_variant and current_persona:
                entries.append(
                    EntryRef(
                        variant_label=current_variant,
                        persona=current_persona,
                        persona_suffix=rpm.persona_to_suffix(current_persona),
                        entry_id=entry_id,
                    )
                )
    return entries


@dataclass
class TargetPath:
    path: Path
    exists: bool


def collect_paths(model_name: str, ref: EntryRef) -> list[TargetPath]:
    targets: list[TargetPath] = []

    # Build name variants to cover hyphen/underscore differences
    name_variants = model_name_variants(model_name)

    # History paths
    hist_candidates = [
        HISTORY_ROOT
        / model_history_dir(mname)
        / ref.variant_label
        / ref.persona_suffix
        / f"{ref.entry_id}.json"
        for mname in name_variants
    ]
    hist_existing = [p for p in hist_candidates if p.exists()]
    if hist_existing:
        targets.extend(TargetPath(p.resolve(), True) for p in hist_existing)
    elif hist_candidates:
        targets.append(TargetPath(hist_candidates[0].resolve(), False))

    # Result paths: canonical + variants under both hyphen and underline model dirs
    candidate_roots = []
    for mname in name_variants:
        candidate_roots.append(RESULT_ROOT / mname / ref.variant_label / ref.persona_suffix)
        candidate_roots.append(RESULT_ROOT / model_history_dir(mname) / ref.variant_label / ref.persona_suffix)
    result_existing: list[TargetPath] = []
    for root in candidate_roots:
        stem = f"{VERSION_PREFIX}_{ref.entry_id}_result"
        canonical = root / f"{stem}.json"
        if canonical.exists():
            result_existing.append(TargetPath(canonical.resolve(), True))
        for p in root.glob(f"{stem}*"):
            if p.name == canonical.name:
                continue
            result_existing.append(TargetPath(p.resolve(), p.exists()))
    if result_existing:
        targets.extend(result_existing)
    elif candidate_roots:
        primary = candidate_roots[0] / f"{VERSION_PREFIX}_{ref.entry_id}_result.json"
        targets.append(TargetPath(primary.resolve(), False))

    # Judge score paths: match *_judge*.json containing the id
    judge_roots = []
    for mname in name_variants:
        judge_roots.append(JUDGE_ROOT / mname / ref.variant_label / ref.persona_suffix)
        judge_roots.append(JUDGE_ROOT / model_history_dir(mname) / ref.variant_label / ref.persona_suffix)
    judge_existing: list[TargetPath] = []
    for root in judge_roots:
        if not root.exists():
            continue
        for p in root.glob("*judge*.json"):
            name = p.name
            if re.search(rf"(^|_){re.escape(ref.entry_id)}(_|\.|$)", name):
                judge_existing.append(TargetPath(p.resolve(), True))
    targets.extend(judge_existing)

    # Deduplicate paths preserving order
    seen = set()
    deduped: list[TargetPath] = []
    for t in targets:
        if t.path in seen:
            continue
        seen.add(t.path)
        deduped.append(t)
    return deduped


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview and delete artifacts for missing <END_SIMULATION> or Error Not Rerun entries."
    )
    parser.add_argument("--model", required=True, help="Model name (e.g., gemini-3-flash-FC)")
    parser.add_argument(
        "--status-file",
        required=True,
        help="Path to file_status_<model>.txt from check_persona_progress.py",
    )
    parser.add_argument(
        "--mode",
        choices=["missing_end", "error_not_rerun"],
        default="missing_end",
        help="Which bucket to target (default missing_end).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete files; otherwise only preview.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    status_path = Path(args.status_file)
    if not status_path.exists():
        print(f"Status file not found: {status_path}", file=sys.stderr)
        return 1

    text = status_path.read_text(encoding="utf-8")
    if args.mode == "missing_end":
        refs = parse_missing_end_section(text)
    else:
        refs = parse_error_not_rerun(text)

    if not refs:
        print("No matching entries found.")
        return 0

    all_paths: list[TargetPath] = []
    per_entry_counts: list[tuple[EntryRef, int, int]] = []  # (entry, ok_paths, missing_paths)
    print("Planned deletions:\n")
    for ref in refs:
        print(f"[{ref.variant_label}/{ref.persona}/{ref.entry_id}]")
        paths = collect_paths(args.model, ref)
        if not paths:
            print("  (no paths)")
        for tp in paths:
            status = "OK" if tp.exists else "MISSING"
            print(f"  [{status}] {tp.path}")
        print()
        all_paths.extend(paths)
        ok_count = sum(1 for tp in paths if tp.exists)
        missing_count = sum(1 for tp in paths if not tp.exists)
        per_entry_counts.append((ref, ok_count, missing_count))

    total_ok_entries = sum(1 for _, ok, _ in per_entry_counts if ok > 0)
    total_ok_paths = sum(ok for _, ok, _ in per_entry_counts)
    print(f"Total entries: {len(refs)} (with existing files: {total_ok_entries}, OK paths: {total_ok_paths})")
    for ref, ok_count, missing_count in per_entry_counts:
        print(
            f"  - {ref.variant_label}/{ref.persona}/{ref.entry_id}: OK={ok_count}, Missing={missing_count}"
        )
    print("")

    if not args.execute:
        print("Preview only (no deletion). Re-run with --execute to delete after confirming.")
        return 0

    answer = input("Proceed to delete the above files? [y/N]: ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborted.")
        return 0

    deleted = 0
    missing = 0
    for tp in all_paths:
        try:
            tp.path.unlink()
            deleted += 1
        except FileNotFoundError:
            missing += 1
        except Exception as exc:  # pragma: no cover
            print(f"Failed to delete {tp.path}: {exc}", file=sys.stderr)
    print(f"Deleted: {deleted}, Missing: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
