from __future__ import annotations

import shutil
import argparse
import sys
from pathlib import Path


def _normalize_model_name(model_name: str) -> str:
    """Match BaseHandler normalization: replace / - . with underscores."""
    return model_name.replace("/", "_").replace("-", "_").replace(".", "_")


def _copy_template(template_dir: Path, target_dir: Path, overwrite: bool = False) -> bool:
    """Copy template files into target, optionally preserving existing files."""
    target_dir.mkdir(parents=True, exist_ok=True)
    copied_any = False

    for src in template_dir.rglob("*"):
        rel = src.relative_to(template_dir)
        dest = target_dir / rel

        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue

        if dest.exists() and not overwrite:
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied_any = True

    return copied_any


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap user_simulator history for a model from history_template."
    )
    parser.add_argument("--model", required=True, help="Model name to normalize and create history folders for.")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing history files (default: keep existing files and copy only missing ones).",
    )
    args = parser.parse_args()

    history_root = Path(__file__).resolve().parents[1] / "bfcl_eval" / "user_simulator" / "history"
    template_dir = history_root / "history_template"
    if not template_dir.exists():
        print(f"[error] Template not found: {template_dir}", file=sys.stderr)
        return 1
    if not template_dir.is_dir():
        print(f"[error] Template path is not a directory: {template_dir}", file=sys.stderr)
        return 1

    normalized = _normalize_model_name(args.model)
    model_root = history_root / normalized

    for flavor in ("personalization", "no_personalization"):
        target = model_root / flavor
        copied = _copy_template(template_dir, target, overwrite=args.overwrite)
        if copied:
            status = "[ok]"
            detail = "Populated (existing files preserved)" if not args.overwrite else "Populated"
        else:
            status = "[skip]"
            detail = "Already exists, not overwriting"
        print(f"{status} {detail}: {target}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
