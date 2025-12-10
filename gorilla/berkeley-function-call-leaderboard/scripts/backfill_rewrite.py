"""
Backfill missing fields (e.g., function/initial_config/involved_classes) from the original
multi-turn dataset into its rewritten counterpart that only has high_level_instruction.

Usage example:
python scripts/backfill_rewrite.py \
  --original /path/to/BFCL_v3_multi_turn_long_context.json \
  --rewrite /path/to/BFCL_v3_multi_turn_long_context_rewrite.json \
  --out /path/to/BFCL_v3_multi_turn_long_context_rewrite_filled.json

The script:
- Loads both files (supports JSON array or JSONL).
- Matches entries by "id".
- For each rewrite entry, copies over the specified keys if they are missing.
- Writes output in the same structural format as the rewrite input (JSON array or JSONL).
"""

import argparse
import json
from pathlib import Path
from typing import Iterable, List, Tuple


def load_entries(path: Path) -> Tuple[List[dict], str]:
    """
    Load entries from JSON array or JSONL. Returns (entries, format), format in {"json", "jsonl"}.
    """
    raw = path.read_text()
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data, "json"
    except json.JSONDecodeError:
        pass

    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries, "jsonl"


def dump_entries(entries: Iterable[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(list(entries), ensure_ascii=False, indent=2)
    elif fmt == "jsonl":
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def backfill(original_entries: List[dict], rewrite_entries: List[dict], keys: Iterable[str]) -> List[dict]:
    orig_by_id = {e.get("id"): e for e in original_entries if "id" in e}
    filled = []

    for entry in rewrite_entries:
        entry_id = entry.get("id")
        if entry_id is None:
            filled.append(entry)
            continue

        orig = orig_by_id.get(entry_id)
        if not orig:
            filled.append(entry)
            continue

        merged = dict(entry)
        for key in keys:
            if key not in merged and key in orig:
                merged[key] = orig[key]
        filled.append(merged)

    return filled


def main():
    parser = argparse.ArgumentParser(description="Backfill missing fields in rewrite dataset from original dataset.")
    parser.add_argument("--original", required=True, type=Path, help="Path to original BFCL dataset (JSON or JSONL).")
    parser.add_argument("--rewrite", required=True, type=Path, help="Path to rewritten dataset (JSON or JSONL).")
    parser.add_argument(
        "--out",
        type=Path,
        help="Output path. If omitted, will overwrite the rewrite file.",
    )
    parser.add_argument(
        "--keys",
        nargs="+",
        default=["function", "initial_config", "involved_classes"],
        help="Keys to backfill when missing in the rewrite entries.",
    )
    args = parser.parse_args()

    original_entries, _ = load_entries(args.original)
    rewrite_entries, rewrite_fmt = load_entries(args.rewrite)

    filled_entries = backfill(original_entries, rewrite_entries, args.keys)

    out_path = args.out or args.rewrite
    out_path.write_text(dump_entries(filled_entries, rewrite_fmt))
    print(f"Wrote filled rewrite dataset to {out_path} ({len(filled_entries)} entries).")


if __name__ == "__main__":
    main()
