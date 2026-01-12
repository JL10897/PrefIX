from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from bfcl_eval.constants.eval_config import LLM_JUDGE_SCORE_PATH, PACKAGE_ROOT

HISTORY_ROOT = PACKAGE_ROOT / "user_simulator" / "history"


def _list_missing_for_model(
    model_dir: Path, target_personalization: str | None
) -> List[Path]:
    missing: List[Path] = []
    for personalization_dir in model_dir.iterdir():
        if not personalization_dir.is_dir():
            continue
        personalization_flag = personalization_dir.name  # personalization / no_personalization
        if target_personalization and personalization_flag != target_personalization:
            continue
        for persona_dir in personalization_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            persona = persona_dir.name
            for history_file in persona_dir.glob("*.json"):
                test_id = history_file.stem
                expected = (
                    LLM_JUDGE_SCORE_PATH
                    / model_dir.name
                    / personalization_flag
                    / persona
                    / f"{test_id}_judge.json"
                )
                if not expected.exists():
                    missing.append(expected)
    return missing


def main(model: str | None = None, personalization: str | None = None) -> None:
    targets: List[Path] = []
    if model:
        mdir = HISTORY_ROOT / model
        if mdir.is_dir():
            targets.append(mdir)
    else:
        targets = [p for p in HISTORY_ROOT.iterdir() if p.is_dir()]

    target_personalization = personalization if personalization in (
        "personalization",
        "no_personalization",
    ) else None

    missing_all: List[Path] = []
    for mdir in targets:
        missing_all.extend(_list_missing_for_model(mdir, target_personalization))

    if not missing_all:
        print("All history files have corresponding judge outputs.")
        return

    print("Missing judge outputs:")
    for path in missing_all:
        print(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="List history entries that do not have LLM judge outputs."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Specific model directory under user_simulator/history to check.",
    )
    parser.add_argument(
        "--personalization",
        type=str,
        choices=["personalization", "no_personalization"],
        default=None,
        help="Optional filter for personalization flag.",
    )
    args = parser.parse_args()
    main(model=args.model, personalization=args.personalization)
