from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parent
SYSTEM_PROMPT_FILE = "system_prompt.txt"
SYSTEM_PROMPT_BASE_FILE = "system_prompt_base.txt"
SYSTEM_PROMPT_PERSONALIZATION_FILE = "system_prompt_personalization.txt"
INTERACTION_INSTRUCTION_FILE = "interaction_instruction.md"
INTERACTION_HISTORY_FILE = "interaction_history.txt"
PROMPTS_DIR_ENV = "BFCL_PROMPTS_DIR"


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def _normalize_prompts(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _resolve_prompts_dir() -> Path:
    env_dir = os.getenv(PROMPTS_DIR_ENV)
    if env_dir:
        candidate = Path(env_dir).expanduser().resolve()
        if candidate.exists():
            return candidate
    return DEFAULT_PROMPTS_DIR


@lru_cache(maxsize=4)
def _format_history_filename(suffix: str | None) -> str:
    """
    Build interaction history filename from optional suffix.
    """
    if not suffix:
        return INTERACTION_HISTORY_FILE
    cleaned = str(suffix).strip().lower().replace(" ", "_")
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in ("_", "-"))
    if not cleaned:
        return INTERACTION_HISTORY_FILE
    return f"interaction_history_{cleaned}.txt"


def load_prompt_bundle(
    prompts_dir: Path | None = None,
    personalization_enabled: bool = True,
    interaction_history_suffix: str | None = None,
) -> dict:
    """
    Load prompt components (system prompt, interaction instruction, interaction history)
    from text files. Returns a dict with list-valued fields for easy concatenation.
    """
    base_dir = prompts_dir or _resolve_prompts_dir()
    system_prompt_file = (
        SYSTEM_PROMPT_PERSONALIZATION_FILE if personalization_enabled else SYSTEM_PROMPT_BASE_FILE
    )
    system_prompt = _read_text_file(base_dir / system_prompt_file)
    interaction_instruction = _read_text_file(base_dir / INTERACTION_INSTRUCTION_FILE)

    history_file = _format_history_filename(interaction_history_suffix)
    preference_dir = base_dir / "Preference_Interaction_History"
    candidate_paths = []
    if interaction_history_suffix:
        candidate_paths.append(preference_dir / history_file)
    candidate_paths.append(base_dir / history_file)
    for path in candidate_paths:
        interaction_history = _read_text_file(path)
        if interaction_history:
            break
    else:
        interaction_history = ""
    if not interaction_history and history_file != INTERACTION_HISTORY_FILE:
        # Fallback to default if the requested variant is missing.
        interaction_history = _read_text_file(base_dir / INTERACTION_HISTORY_FILE)

    return {
        "system_prompts": _normalize_prompts(system_prompt),
        "interaction_instructions": _normalize_prompts(interaction_instruction),
        # Interaction history can be treated like prompts (prepended once).
        "interaction_history": _normalize_prompts(interaction_history),
    }
