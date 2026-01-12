from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from bfcl_eval.constants.eval_config import (
    LLM_JUDGE_SCORE_PATH,
    PACKAGE_ROOT,
    PROJECT_ROOT,
)
from bfcl_eval.eval_checker.LLM_as_a_judge.gemini_judge import JudgmentResult
from bfcl_eval.eval_checker.LLM_as_a_judge.openrouter_judge import (
    generate_judgment_with_openrouter,
)

HISTORY_ROOT = PACKAGE_ROOT / "user_simulator" / "history"
PERSONA_DESC_PATH = Path(__file__).with_name("persona_descriptions.json")


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
        # function_call_output entries place payload under "output"
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


def run_for_model(
    model_dir: Path,
    allowed_personalization: set[str] | None = None,
    judge_model: str = "openai/gpt-5.2",
    persona_profiles: Dict[str, Dict[str, Any]] | None = None,
    max_output_tokens: int = 2048,
    max_transcript_chars: int = 8000,
    skip_existing: bool = False,
    personas_filter: List[str] | None = None,
) -> None:
    """Run Gemini judge for all history files under a model directory."""
    model_dir_name = model_dir.name
    judge_dir_name = _normalize_judge_model_name(judge_model)
    target_dims = [
        "initiative_timing",
        "interaction_coherence",
        "intent_alignment_drift",
        "commitment_consistency",
        "interaction_efficiency",
        "user_cognitive_load_trajectory",
        "interaction_preference_alignment",
        "overall_user_experience",
    ]
    regenerated: list[str] = []
    for personalization_dir in model_dir.iterdir():
        if not personalization_dir.is_dir():
            continue
        personalization_flag = personalization_dir.name  # personalization / no_personalization
        if allowed_personalization and personalization_flag not in allowed_personalization:
            continue
        for persona_dir in personalization_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            persona = persona_dir.name
            normalized_persona = persona.lower().replace(" ", "_")
            if personas_filter:
                allowed_personas = {p.lower().replace(" ", "_") for p in personas_filter}
                if normalized_persona not in allowed_personas:
                    continue
            if not persona_profiles:
                raise ValueError("Persona profiles are empty; ensure persona_descriptions.json is populated.")
            persona_profile = persona_profiles.get(normalized_persona)
            if not persona_profile:
                raise ValueError(f"Persona description not found for '{persona}' (normalized '{normalized_persona}').")
            persona_description = persona_profile.get("description")
            if not persona_description:
                raise ValueError(f"Persona description is empty for '{persona}' (normalized '{normalized_persona}').")
            persona_trajectory = _format_persona_trajectory(persona_profile)
            for history_file in persona_dir.glob("*.json"):
                test_id = history_file.stem
                transcript = _parse_history_file(history_file)
                if not transcript:
                    continue
                output_dir = (
                    LLM_JUDGE_SCORE_PATH
                    / judge_dir_name
                    / model_dir_name
                    / personalization_flag
                    / persona
                )
                out_file = output_dir / f"{test_id}_judge.json"
                if skip_existing and out_file.exists():
                    try:
                        existing = json.loads(out_file.read_text(encoding="utf-8"))
                        dims = existing.get("parsed", {}).get("dimensions", {})
                        if all(
                            dim in dims and dims.get(dim, {}).get("score") is not None for dim in target_dims
                        ):
                            continue
                    except Exception:
                        pass
                judge_result = generate_judgment_with_openrouter(
                    transcript=transcript,
                    persona=persona,
                    persona_description=persona_description,
                    persona_trajectory=persona_trajectory,
                    model_name=judge_model,
                    max_output_tokens=max_output_tokens,
                    max_transcript_chars=max_transcript_chars,
                )
                _write_result(
                    output_dir=output_dir,
                    test_id=test_id,
                    persona=persona,
                    personalization_flag=personalization_flag,
                    model_dir_name=model_dir_name,
                    result=judge_result,
                )
                regenerated.append(str(out_file))
    if regenerated:
        print("Regenerated judge outputs:")
        for path in regenerated:
            print(f"- {path}")


def main(
    model: str | None = None,
    personalization: str = "all",
    judge_model: str = "openai/gpt-5.2",
    max_output_tokens: int = 4096,
    max_transcript_chars: int = 8000,
    skip_existing: bool = False,
    personas: List[str] | None = None,
) -> None:
    target_dirs = []
    if model:
        target = HISTORY_ROOT / model
        if target.is_dir():
            target_dirs.append(target)
    else:
        target_dirs = [p for p in HISTORY_ROOT.iterdir() if p.is_dir()]

    allowed_personalization: set[str] | None = None
    if personalization in ("personalization", "no_personalization"):
        allowed_personalization = {personalization}

    persona_profiles = _load_persona_profiles()

    for model_dir in target_dirs:
        run_for_model(
            model_dir,
            allowed_personalization=allowed_personalization,
            judge_model=judge_model,
            persona_profiles=persona_profiles,
            max_output_tokens=max_output_tokens,
            max_transcript_chars=max_transcript_chars,
            skip_existing=skip_existing,
            personas_filter=personas,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run Gemini 3 Pro judge over user_simulator histories."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Specific model directory name under bfcl_eval/user_simulator/history. If omitted, run all.",
    )
    parser.add_argument(
        "--personalization",
        type=str,
        choices=["personalization", "no_personalization", "all"],
        default="all",
        help="Run only personalization, only no_personalization, or all (default).",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default="openai/gpt-5.2",
        help="Judge model name to call (OpenRouter id, default openai/gpt-5.2).",
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
        help="Skip history files that already have a judge output.",
    )
    parser.add_argument(
        "--personas",
        type=str,
        default=None,
        help="Comma-separated persona names to include (match directory names). If omitted, all personas are processed.",
    )
    args = parser.parse_args()
    personas_list = [p.strip() for p in args.personas.split(",")] if args.personas else None
    main(
        model=args.model,
        personalization=args.personalization,
        judge_model=args.judge_model,
        max_output_tokens=args.max_output_tokens,
        max_transcript_chars=args.max_transcript_chars,
        skip_existing=args.skip_existing,
        personas=personas_list,
    )
