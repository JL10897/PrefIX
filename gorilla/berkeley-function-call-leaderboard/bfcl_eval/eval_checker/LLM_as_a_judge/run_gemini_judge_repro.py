from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from bfcl_eval.constants.eval_config import PACKAGE_ROOT, PROJECT_ROOT
from bfcl_eval.eval_checker.LLM_as_a_judge.openrouter_judge import (
    JudgmentResult,
    generate_judgment_with_openrouter,
)

# Fixed target: first N histories in the given directory.
TARGET_HISTORY_DIR = (
    PACKAGE_ROOT
    / "user_simulator"
    / "history"
    / "claude_opus_4_5_20251101_FC"
    / "personalization"
    / "tool_high"
)

# Repro output root.
REPRO_OUTPUT_ROOT = PROJECT_ROOT / "LLM_as_judge_score_repro"
REPRO_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

# Defaults for reproducibility runs.
DEFAULT_HISTORY_LIMIT = 5
DEFAULT_RUN_COUNT = 20

PERSONA_DESC_PATH = Path(__file__).with_name("persona_descriptions.json")

TARGET_DIMS = [
    "initiative_timing",
    "interaction_coherence",
    "intent_alignment_drift",
    "commitment_consistency",
    "interaction_efficiency",
    "user_cognitive_load_trajectory",
    "interaction_preference_alignment",
    "overall_user_experience",
]


def _normalize_judge_model_name(model_name: str) -> str:
    """Make judge model name safe to use as a directory component."""
    return (
        model_name.strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace(":", "_")
    )


def _extract_content(node: Any) -> str:
    """Extract text content from user_simulator history entries."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        parts: List[str] = []
        for item in node:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item.get("text", "")))
                elif "content" in item:
                    parts.append(str(item.get("content", "")))
        return "\n".join(parts)
    if isinstance(node, dict):
        if "output" in node:
            return str(node.get("output", ""))
        if "content" in node:
            return _extract_content(node.get("content"))
    return str(node)


def _parse_history_file(path: Path) -> List[Dict[str, Any]]:
    """Parse a single history file into transcript turns."""
    transcript: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            turn_id = f"t{idx}"
            role = obj.get("role") or obj.get("class_name") or "unknown"
            kind = "system"

            if obj.get("type") == "function_call_output":
                role = "tool"
                kind = "function_call_output"
            elif role == "user":
                kind = "user_message"
            elif role == "assistant":
                kind = "assistant_message"
            elif role == "tool":
                kind = "tool_output"

            content = _extract_content(obj.get("content", obj.get("output", "")))

            transcript.append(
                {
                    "turn_id": turn_id,
                    "role": role,
                    "kind": kind,
                    "content": content,
                }
            )
    return transcript


def _load_persona_profiles() -> Dict[str, Dict[str, Any]]:
    """Load persona descriptions and map by normalized key (lowercase with underscores)."""
    if not PERSONA_DESC_PATH.exists():
        raise FileNotFoundError(f"persona_descriptions.json not found at {PERSONA_DESC_PATH}")
    try:
        profiles = json.loads(PERSONA_DESC_PATH.read_text(encoding="utf-8"))
    except Exception:
        raise Exception("No Persona loaded")
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in profiles:
        name = item.get("persona", "")
        key = name.lower().replace(" ", "_")
        mapping[key] = item
    return mapping


def _format_persona_trajectory(persona_profile: Dict[str, Any]) -> str:
    """Serialize trajectory hints from persona profile (keys starting with 'trajectory')."""
    parts: List[str] = []
    for key, value in persona_profile.items():
        if not key.startswith("trajectory"):
            continue
        if isinstance(value, list):
            serialized = " -> ".join(str(v) for v in value)
            parts.append(f"{key}: {serialized}")
    return "\n".join(parts)


def _write_result(
    output_dir: Path,
    test_id: str,
    persona: str,
    personalization_flag: str,
    model_dir_name: str,
    result: JudgmentResult,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_id": test_id,
        "model_dir": model_dir_name,
        "persona": persona,
        "personalization": personalization_flag,
        "parsed": result.parsed,
        "raw_response_text": result.raw_response_text,
        "request_payload": result.request_payload,
        "latency_seconds": result.latency_seconds,
        "errors": result.errors,
        "truncated": result.truncated,
    }
    out_file = output_dir / f"{test_id}_judge.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _select_histories(history_dir: Path, limit: int) -> List[Path]:
    """Pick the first N histories (sorted) from the target directory."""
    files = sorted(history_dir.glob("*.json"))
    return files[:limit]


def run_repro(
    judge_model: str = "anthropic/claude-sonnet-4.5",
    max_output_tokens: int = 4096,
    max_transcript_chars: int = 8000,
    skip_existing: bool = False,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    run_count: int = DEFAULT_RUN_COUNT,
) -> None:
    """Run multiple LLM-judge passes for reproducibility on the fixed dataset."""
    if not TARGET_HISTORY_DIR.exists():
        raise FileNotFoundError(f"Target history directory not found: {TARGET_HISTORY_DIR}")

    persona_profiles = _load_persona_profiles()
    persona_name = TARGET_HISTORY_DIR.name
    persona_key = persona_name.lower().replace(" ", "_")
    persona_profile = persona_profiles.get(persona_key)
    if not persona_profile:
        raise ValueError(f"Persona description not found for '{persona_name}'")
    persona_description = persona_profile.get("description", "")
    if not persona_description:
        raise ValueError(f"Persona description is empty for '{persona_name}'")
    persona_trajectory = _format_persona_trajectory(persona_profile)

    history_files = _select_histories(TARGET_HISTORY_DIR, history_limit)
    if not history_files:
        raise ValueError(f"No history files found under {TARGET_HISTORY_DIR}")

    judge_dir_name = _normalize_judge_model_name(judge_model)
    model_dir_name = TARGET_HISTORY_DIR.parent.parent.name
    personalization_flag = TARGET_HISTORY_DIR.parent.name

    regenerated: List[str] = []

    for run_index in range(1, run_count + 1):
        run_root = REPRO_OUTPUT_ROOT / f"repro_{run_index}" / judge_dir_name
        for history_file in history_files:
            test_id = history_file.stem
            transcript = _parse_history_file(history_file)
            if not transcript:
                continue
            output_dir = run_root / model_dir_name / personalization_flag / persona_name
            out_file = output_dir / f"{test_id}_judge.json"

            if skip_existing and out_file.exists():
                try:
                    existing = json.loads(out_file.read_text(encoding="utf-8"))
                    dims = existing.get("parsed", {}).get("dimensions", {})
                    if all(dim in dims and dims.get(dim, {}).get("score") is not None for dim in TARGET_DIMS):
                        continue
                except Exception:
                    pass

            judge_result = generate_judgment_with_openrouter(
                transcript=transcript,
                persona=persona_name,
                persona_description=persona_description,
                persona_trajectory=persona_trajectory,
                model_name=judge_model,
                max_output_tokens=max_output_tokens,
                max_transcript_chars=max_transcript_chars,
            )
            _write_result(
                output_dir=output_dir,
                test_id=test_id,
                persona=persona_name,
                personalization_flag=personalization_flag,
                model_dir_name=model_dir_name,
                result=judge_result,
            )
            regenerated.append(str(out_file))

    if regenerated:
        print("Generated judge outputs:")
        for path in regenerated:
            print(f"- {path}")
    else:
        print("No outputs generated (no histories or all skipped).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run reproducibility sweeps for LLM-as-judge on fixed histories."
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="anthropic/claude-sonnet-4.5",
        help="Judge model name to call (OpenRouter id).",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=4096,
        help="Max output tokens for the judge model (default 4096).",
    )
    parser.add_argument(
        "--max-transcript-chars",
        type=int,
        default=8000,
        help="Max transcript characters to pass into the judge prompt (default 8000).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip history files that already have a judge output for that run.",
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=DEFAULT_HISTORY_LIMIT,
        help="Number of histories (sorted) from the target directory to evaluate.",
    )
    parser.add_argument(
        "--run-count",
        type=int,
        default=DEFAULT_RUN_COUNT,
        help="How many reproducibility runs to perform.",
    )
    args = parser.parse_args()
    run_repro(
        judge_model=args.judge_model,
        max_output_tokens=args.max_output_tokens,
        max_transcript_chars=args.max_transcript_chars,
        skip_existing=args.skip_existing,
        history_limit=args.history_limit,
        run_count=args.run_count,
    )


if __name__ == "__main__":
    main()
