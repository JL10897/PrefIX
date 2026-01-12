"""
Standalone single-sample runner for multi_turn_checker.
Accepts either an explicit result file path or a tuple of
(model, personalization_setting, persona, sample_name) and builds
the expected BFCL result file path automatically.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Allow running without setting PYTHONPATH by injecting repo root early
CURRENT_DIR = Path(__file__).resolve()
PROJECT_ROOT_LOCAL = CURRENT_DIR.parents[3]  # /gorilla/berkeley-function-call-leaderboard
if str(PROJECT_ROOT_LOCAL) not in sys.path:
    sys.path.append(str(PROJECT_ROOT_LOCAL))

from bfcl_eval.constants.category_mapping import VERSION_PREFIX
from bfcl_eval.constants.eval_config import (
    POSSIBLE_ANSWER_PATH,
    PROJECT_ROOT,
    PROMPT_PATH,
    RESULT_PATH,
)
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_checker import (
    multi_turn_checker_full_list,
)
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import (
    is_empty_execute_response,
)
from bfcl_eval.model_handler.utils import convert_to_function_call
from bfcl_eval.utils import extract_test_category_from_id, load_file


def _decode_multi_turn(model_result_list: List[List]) -> List[List[List[str]]]:
    decoded: List[List[List[str]]] = []
    for single_turn_model_result_list in model_result_list:
        single_turn_decoded: List[List[str]] = []
        for model_result_item in single_turn_model_result_list:
            try:
                decoded_result: List[str] = convert_to_function_call(model_result_item)
            except Exception:
                continue
            if is_empty_execute_response(decoded_result):
                continue
            single_turn_decoded.append(decoded_result)
        decoded.append(single_turn_decoded)
    return decoded


def _load_single_result(result_path: Path, sample_id: Optional[str]) -> Dict:
    data = load_file(result_path)
    if isinstance(data, list):
        if sample_id is None and len(data) == 1 and "id" in data[0]:
            return data[0]
        if sample_id is None:
            raise ValueError("sample_id is required when result file contains multiple entries.")
        for entry in data:
            if entry.get("id") == sample_id:
                return entry
        raise ValueError(f"sample_id {sample_id} not found in result file.")
    if isinstance(data, dict):
        if sample_id is not None and data.get("id") != sample_id:
            raise ValueError(f"sample_id mismatch: expected {sample_id}, got {data.get('id')}")
        if "id" not in data or "result" not in data:
            raise ValueError("result file dict must contain 'id' and 'result' keys.")
        return data
    raise ValueError("Unsupported result file format; expected list or dict JSON.")


def _normalize_filename(sample_name: str) -> str:
    name = sample_name
    if name.endswith(".json"):
        return name
    if name.startswith("BFCL_"):
        if name.endswith("_result.json"):
            return name
        if name.endswith("_result"):
            return f"{name}.json"
        return f"{name}_result.json"
    # bare sample id, prepend version prefix
    return f"{VERSION_PREFIX}_{name}_result.json"


def _resolve_result_path(
    model_name: str,
    personalization_setting: Optional[str],
    persona: Optional[str],
    sample_name: Optional[str],
    explicit_result_file: Optional[Path],
) -> Path:
    if explicit_result_file is not None:
        return explicit_result_file
    if not (personalization_setting and persona and sample_name):
        raise ValueError(
            "Either --result-file or all of (--personalization-setting, --persona, --sample-name) must be provided."
        )

    filename = _normalize_filename(sample_name)
    return RESULT_PATH / model_name / personalization_setting / persona / filename


def main(
    model_name: str,
    personalization_setting: Optional[str],
    persona: Optional[str],
    sample_name: Optional[str],
    result_path: Optional[Path],
    sample_id: Optional[str] = None,
):
    # Ensure repo root on sys.path for direct script runs without PYTHONPATH export
    repo_root = PROJECT_ROOT
    if str(repo_root) not in sys.path:
        sys.path.append(str(repo_root))

    resolved_path = _resolve_result_path(
        model_name=model_name,
        personalization_setting=personalization_setting,
        persona=persona,
        sample_name=sample_name,
        explicit_result_file=result_path,
    )

    if not resolved_path.exists():
        raise FileNotFoundError(f"Result file not found: {resolved_path}")

    model_entry = _load_single_result(resolved_path, sample_id)
    test_id = model_entry["id"]
    model_result_list = model_entry["result"]

    test_category = extract_test_category_from_id(test_id)
    prompt_entries = load_file(PROMPT_PATH / f"{VERSION_PREFIX}_{test_category}.json")
    gt_entries = load_file(POSSIBLE_ANSWER_PATH / f"{VERSION_PREFIX}_{test_category}.json")

    prompt_entry = next((p for p in prompt_entries if p.get("id") == test_id), None)
    gt_entry = next((g for g in gt_entries if g.get("id") == test_id), None)
    if prompt_entry is None or gt_entry is None:
        raise ValueError(
            f"Prompt/ground truth entry with id {test_id} not found for category {test_category}."
        )

    decoded = _decode_multi_turn(model_result_list)
    checker_result = multi_turn_checker_full_list(
        decoded,
        gt_entry["ground_truth"],
        prompt_entry,
        test_category,
        model_name,
    )

    summary = {
        "id": test_id,
        "result_file": str(resolved_path),
        "valid": checker_result.get("valid"),
        # "details":checker_result.get("details")
    }
    # Include minimal error context if invalid
    if not checker_result.get("valid"):
        summary["error_type"] = checker_result.get("error_type")
        summary["error_message"] = checker_result.get("error_message")
        summary["unmatched_ground_truth_turns"] = checker_result.get("details").get("unmatched_ground_truth_turns")
        summary["multi_turn_model_result_list_decoded"] = checker_result.get("details").get("multi_turn_model_result_list_decoded")
        summary["multi_turn_ground_truth_list"] = checker_result.get("details").get("multi_turn_ground_truth_list")
    # 更美观地输出JSON，支持嵌套、自动颜色和缩进（如果在控制台/终端使用）
    try:
        import rich
        from rich import print as rprint
        from rich.pretty import Pretty
        rprint(Pretty(summary, indent_guides=True, max_depth=6))
    except ImportError:
        # Fallback to basic pretty json
        print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run multi_turn_checker on a single sample result file."
    )
    parser.add_argument("--model", required=True, help="Model name.")
    parser.add_argument(
        "--result-file",
        default=None,
        type=Path,
        help="Optional: explicit path to a single-sample result JSON.",
    )
    parser.add_argument(
        "--personalization-setting",
        help="personalization | no_personalization | other setting name",
    )
    parser.add_argument("--persona", help="Persona folder name, e.g., chain_parallel")
    parser.add_argument("--sample-name", help="Sample name, e.g., multi_turn_long_context_182")
    parser.add_argument(
        "--sample-id",
        default=None,
        help="Sample id; required if result file has multiple entries.",
    )
    args = parser.parse_args()
    main(
        model_name=args.model,
        personalization_setting=args.personalization_setting,
        persona=args.persona,
        sample_name=args.sample_name,
        result_path=args.result_file,
        sample_id=args.sample_id,
    )
