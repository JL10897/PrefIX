import re
from collections import Counter


def normalize_call_str(call_str: str) -> str:
    """
    Light-weight normalization to reduce formatting noise while preserving argument values.
    - Strips outer whitespace
    - Removes spaces around parentheses, commas, and equals
    """
    s = call_str.strip()
    # Remove spaces before/after parentheses and commas
    s = re.sub(r"\s*,\s*", ",", s)
    s = re.sub(r"\(\s*", "(", s)
    s = re.sub(r"\s*\)", ")", s)
    # Remove spaces around equals
    s = re.sub(r"\s*=\s*", "=", s)
    return s


def flatten_model_calls(model_calls: list) -> list[str]:
    """
    Flattens model calls shaped like [[["a()"], ["b()"]], ...] into 1-D strings.
    """
    flat: list[str] = []
    for turn_calls in model_calls or []:
        for step_calls in turn_calls or []:
            # step_calls is expected to be a list of call strings
            for call in step_calls or []:
                if call is None:
                    continue
                call_str = str(call).strip()
                if call_str:
                    flat.append(call_str)
    return flat


def flatten_ground_truth_calls(gt_calls: list) -> list[str]:
    """
    Flattens ground truth shaped like [["a()"], ["b()", "c()"], ...] into 1-D strings.
    """
    flat: list[str] = []
    for turn_calls in gt_calls or []:
        for call in turn_calls or []:
            if call is None:
                continue
            call_str = str(call).strip()
            if call_str:
                flat.append(call_str)
    return flat


def compute_unordered_coverage(model_calls: list[str], gt_calls: list[str]) -> dict:
    """
    Unordered coverage using Counters. Counts duplicates; does not assume ordering.
    Returns match/total/coverage plus missing/extra breakdown.
    """
    model_counter = Counter(model_calls)
    gt_counter = Counter(gt_calls)

    matched = sum(min(model_counter[k], v) for k, v in gt_counter.items())
    total = sum(gt_counter.values())
    coverage = (matched / total) if total else 0.0

    missing = []
    for k, v in gt_counter.items():
        diff = v - model_counter.get(k, 0)
        if diff > 0:
            missing.extend([k] * diff)

    extra = []
    for k, v in model_counter.items():
        diff = v - gt_counter.get(k, 0)
        if diff > 0:
            extra.extend([k] * diff)

    return {
        "gt_match_count": matched,
        "gt_total": total,
        "gt_coverage": coverage,
        "missing_ground_truth": missing,
        "extra_model_calls": extra,
    }


def multi_turn_checker_ratio(
    multi_turn_model_result_list_decoded: list[list[list[str]]],
    multi_turn_ground_truth_list: list[list[str]],
    test_entry: dict,
    test_category: str,
    model_name: str,
) -> dict:
    """
    Computes coverage ratio between model calls and ground truth calls without executing functions.
    """
    _ = (test_entry, test_category, model_name)  # placeholders for parity with other checkers

    model_flat = flatten_model_calls(multi_turn_model_result_list_decoded)
    gt_flat = flatten_ground_truth_calls(multi_turn_ground_truth_list)

    model_norm = [normalize_call_str(c) for c in model_flat]
    gt_norm = [normalize_call_str(c) for c in gt_flat]

    coverage_result = compute_unordered_coverage(model_norm, gt_norm)
    coverage_result.update(
        {
            "valid": True,
            "normalized_model_calls": model_norm,
            "normalized_ground_truth_calls": gt_norm,
        }
    )
    return coverage_result
