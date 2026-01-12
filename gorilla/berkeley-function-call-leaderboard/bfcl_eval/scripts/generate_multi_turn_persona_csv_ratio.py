import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from bfcl_eval.constants.eval_config import (
    PROJECT_ROOT,
    RESULT_PATH,
    PROMPT_PATH,
    POSSIBLE_ANSWER_PATH,
)
from bfcl_eval.constants.category_mapping import VERSION_PREFIX
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_checker_ratio import (
    multi_turn_checker_ratio,
)
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import (
    is_empty_execute_response,
)
from bfcl_eval.model_handler.utils import convert_to_function_call
from bfcl_eval.utils import (
    extract_test_category,
    extract_test_category_from_id,
    is_multi_turn,
    load_file,
)


PersonaRows = List[Tuple[str, float]]


def _subset_entries_by_model_ids(
    model_result_entries: List[dict],
    prompt_entries: List[dict],
    ground_truth_entries: List[dict] = None,
    allow_missing: bool = True,
):
    if not model_result_entries:
        return [], [] if ground_truth_entries is not None else []

    all_present_ids = {entry["id"]: entry for entry in model_result_entries}

    filtered_prompt_entries: list[dict] = []
    filtered_ground_truth_entries: list[dict] = []
    for idx, prompt_entry in enumerate(prompt_entries):
        if prompt_entry["id"] in all_present_ids:
            filtered_prompt_entries.append(prompt_entry)
            if ground_truth_entries is not None:
                filtered_ground_truth_entries.append(ground_truth_entries[idx])

    return filtered_prompt_entries, filtered_ground_truth_entries


def _read_result_entries(persona_dir: Path) -> Dict[str, List[dict]]:
    entries_by_category: Dict[str, List[dict]] = defaultdict(list)
    for json_file in persona_dir.glob("*.json"):
        test_category = None
        try:
            test_category = extract_test_category(json_file.name)
        except Exception:
            stem = json_file.stem
            if stem.endswith("_result"):
                stem = stem[: -len("_result")]
            parts = stem.split("_")
            if len(parts) >= 3 and parts[0].upper().startswith("BFCL"):
                test_category = "_".join(parts[2:])
        if not test_category:
            continue
        try:
            data = json.loads(json_file.read_text())
        except Exception:
            continue
        base_category = extract_test_category_from_id(test_category)
        entries_by_category[base_category].append(data)

    for cat in entries_by_category:
        entries_by_category[cat].sort(key=lambda x: x.get("id", ""))
    return entries_by_category


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


def _evaluate_persona_category(
    model_name: str,
    test_category: str,
    model_entries: List[dict],
) -> Tuple[PersonaRows, float]:
    if not model_entries:
        return [], 0.0

    prompt_entries = load_file(PROMPT_PATH / f"{VERSION_PREFIX}_{test_category}.json")
    ground_truth_entries = load_file(
        POSSIBLE_ANSWER_PATH / f"{VERSION_PREFIX}_{test_category}.json"
    )

    prompt_entries, ground_truth_entries = _subset_entries_by_model_ids(
        model_entries, prompt_entries, ground_truth_entries, allow_missing=True
    )

    id_to_model_entry = {entry["id"]: entry for entry in model_entries}
    rows: PersonaRows = []
    coverage_sum = 0.0

    for prompt_entry, gt_entry in zip(prompt_entries, ground_truth_entries):
        model_entry = id_to_model_entry[prompt_entry["id"]]
        model_result_list = model_entry["result"]

        decoded = _decode_multi_turn(model_result_list)
        checker_result = multi_turn_checker_ratio(
            decoded,
            gt_entry["ground_truth"],
            prompt_entry,
            test_category,
            model_name,
        )
        coverage = checker_result.get("gt_coverage", 0.0) or 0.0
        rows.append((prompt_entry["id"], coverage))
        coverage_sum += coverage

    return rows, coverage_sum


def _write_persona_csv(rows: PersonaRows, coverage_avg: float, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "pass"])
        for row in rows:
            writer.writerow(row)
        writer.writerow(["accuracy", f"{coverage_avg:.4f}"])


def generate_persona_csvs_for_model_ratio(
    model_name: str,
    result_root: Path = RESULT_PATH,
    output_root: Path = PROJECT_ROOT / "scores_persona",
) -> Path:
    model_result_root = result_root / model_name
    output_root = Path(output_root) / model_name
    persona_accuracy_rows: List[Tuple[str, float, int]] = []
    persona_rows_by_label: Dict[str, Dict[str, float]] = {}

    if not model_result_root.exists():
        raise FileNotFoundError(f"Result directory not found: {model_result_root}")

    for personalization_setting in sorted(p.name for p in model_result_root.iterdir() if p.is_dir()):
        setting_dir = model_result_root / personalization_setting
        for persona_dir in sorted(p for p in setting_dir.iterdir() if p.is_dir()):
            persona_name = persona_dir.name
            entries_by_category = _read_result_entries(persona_dir)
            all_rows: PersonaRows = []
            total = 0
            coverage_sum_total = 0.0

            for test_category, entries in entries_by_category.items():
                if not is_multi_turn(test_category):
                    continue
                rows, coverage_sum = _evaluate_persona_category(
                    model_name, test_category, entries
                )
                all_rows.extend(rows)
                total += len(rows)
                coverage_sum_total += coverage_sum

            coverage_avg = (coverage_sum_total / total) if total else 0.0
            persona_label = f"{personalization_setting}/{persona_name}"
            persona_accuracy_rows.append((persona_label, coverage_avg, total))
            persona_rows_by_label[persona_label] = {pid: passed for pid, passed in all_rows}

            output_path = output_root / personalization_setting / f"{persona_name}.csv"
            _write_persona_csv(all_rows, coverage_avg, output_path)

    agg_path = output_root / "persona_accuracy.csv"
    agg_path.parent.mkdir(parents=True, exist_ok=True)

    def _weighted(rows: List[Tuple[str, float, int]]) -> float:
        total_count = sum(r[2] for r in rows)
        if total_count == 0:
            return 0.0
        return sum(r[1] * r[2] for r in rows) / total_count

    no_persona_rows = [r for r in persona_accuracy_rows if r[0].startswith("no_personalization/")]
    yes_persona_rows = [r for r in persona_accuracy_rows if not r[0].startswith("no_personalization/")]

    baseline_by_persona = {
        label.split("/", 1)[1]: (acc, cnt)
        for label, acc, cnt in persona_accuracy_rows
        if label.startswith("no_personalization/") and "/" in label
    }
    comparison_rows: List[Tuple[str, str, float, float, float, int, int]] = []
    positive_personas = set()
    negative_personas = set()
    negative_sample_ids: List[str] = []

    for label, acc, cnt in persona_accuracy_rows:
        if label.startswith("no_personalization/") or "/" not in label:
            continue
        personalization_setting, persona = label.split("/", 1)
        baseline = baseline_by_persona.get(persona)
        if baseline is None:
            continue
        baseline_acc, baseline_cnt = baseline
        personalization_samples = persona_rows_by_label.get(label, {})
        baseline_samples = persona_rows_by_label.get(f"no_personalization/{persona}", {})
        diff = acc - baseline_acc
        comparison_rows.append(
            (
                persona,
                personalization_setting,
                acc,
                baseline_acc,
                diff,
                cnt,
                baseline_cnt,
            )
        )
        if diff > 0:
            positive_personas.add(persona)
        elif diff < 0:
            negative_personas.add(persona)

        for sample_id, personalization_pass in personalization_samples.items():
            if sample_id not in baseline_samples:
                continue
            baseline_pass = baseline_samples[sample_id]
            if personalization_pass < baseline_pass:
                negative_sample_ids.append(f"{personalization_setting}/{persona}:{sample_id}")

    with agg_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["persona", "accuracy", "total_count"])
        for label, acc, cnt in persona_accuracy_rows:
            writer.writerow([label, f"{acc:.4f}", cnt])

        writer.writerow(["no_personalization", f"{_weighted(no_persona_rows):.4f}", sum(r[2] for r in no_persona_rows)])
        writer.writerow(["personalization", f"{_weighted(yes_persona_rows):.4f}", sum(r[2] for r in yes_persona_rows)])
        writer.writerow(
            [
                "overall",
                f"{_weighted(persona_accuracy_rows):.4f}" if persona_accuracy_rows else "0.0000",
                sum(r[2] for r in persona_accuracy_rows),
            ]
        )

        if comparison_rows:
            writer.writerow([])
            writer.writerow(
                [
                    "persona",
                    "personalization_setting",
                    "personalization_accuracy",
                    "no_personalization_accuracy",
                    "accuracy_diff",
                    "personalization_total_count",
                    "no_personalization_total_count",
                ]
            )
            for (
                persona,
                personalization_setting,
                personalization_acc,
                baseline_acc,
                diff,
                personalization_cnt,
                baseline_cnt,
            ) in comparison_rows:
                writer.writerow(
                    [
                        persona,
                        personalization_setting,
                        f"{personalization_acc:.4f}",
                        f"{baseline_acc:.4f}",
                        f"{diff:.4f}",
                        personalization_cnt,
                        baseline_cnt,
                    ]
                )
            writer.writerow([])
            writer.writerow(["diff>0_personas", ";".join(sorted(positive_personas))])
            writer.writerow(["diff<0_personas", ";".join(sorted(negative_personas))])
            writer.writerow(["diff<0_sample_ids(personalization_vs_no_personalization)", ";".join(sorted(negative_sample_ids))])

    return output_root
