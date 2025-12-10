"""
OpenAI-based user simulator (single-turn generation) for BFCL base handler.

Responsibilities:
- Build simulator prompt (disclaimer + persona + simulator prompt md + dialog history + high-level instruction + termination reminder).
- Call OpenAI Responses API (temperature=0) and return a user message.
- Detect termination token (<END_SIMULATION>) in the generated user content.

Non-responsibilities:
- No batching over dataset entries.
- No persistence of history or loop control.
- No tool exposure.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(
    "/Users/JL/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/gorilla/berkeley-function-call-leaderboard"
)
PROMPT_BASE = ROOT / "bfcl_eval/user_simulator/simulator_prompt.md"
PERSONA_PATH = ROOT / "bfcl_eval/user_simulator/persona_prompt.md"
ENV_PATH = ROOT / ".env"

DISCLAIMER = (
    "Your preference shapes your tone and reactions and may potentially affect how you devise the tasks. "
    "Your initiative preference affects only your interaction style, not the task scope. "
    "Do not push the agent to take actions outside the defined task goal."
)

TERMINATION_TOKEN = "<END_SIMULATION>"


def _read_text(path: Path, default: str = "") -> str:
    return path.read_text() if path.exists() else default


def _load_personas(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text()
    # Try full file and substring after first '['
    for candidate in (text, text[text.find("[") :] if "[" in text else ""):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "personas" in data:
                return data["personas"]
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            continue
    return []


def _pick_persona(personas: List[Dict[str, Any]], name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    for p in personas:
        if p.get("persona") == name:
            return p
    return None


def _format_history_block(history: List[dict]) -> str:
    if not history:
        return "<dialog_history>\n[]\n</dialog_history>"
    lines = []
    for m in history:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        lines.append(f"{role}: {content}")
    return "<dialog_history>\n" + "\n".join(lines) + "\n</dialog_history>"


def _assemble_prompt(
    high_level: str, persona: Optional[Dict[str, Any]], history: List[dict]
) -> str:
    persona_text = ""
    if persona:
        behaviors = (
            persona.get("behaviors")
            or persona.get("sample behaviors")
            or []
        )
        behaviors_str = "; ".join(behaviors)
        persona_text = (
            f"You now have the following preferences: {persona.get('description', '')} "
            f"Sample behaviors include (but are not limited to): {behaviors_str}"
        )

    parts = [
        DISCLAIMER,
        persona_text,
        _read_text(PROMPT_BASE, "User simulator: produce the next user turn."),
        "Past history between the user and the model:",
        _format_history_block(history),
        f"High-level instruction: {high_level}",
        f"When you determine the task is fully expressed, output exactly the termination token {TERMINATION_TOKEN}.",
        "Return only the next user turn message.",
    ]
    return "\n".join([p for p in parts if p])


class OpenAIUserSimulator:
    def __init__(self, model_name: str, persona_name: Optional[str] = None) -> None:
        load_dotenv(dotenv_path=ENV_PATH, verbose=True, override=True)
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        self.client = OpenAI(api_key=api_key)
        self.model_name = model_name
        self.persona_name = persona_name
        self.personas = _load_personas(PERSONA_PATH)
        self.persona = _pick_persona(self.personas, persona_name)

    def generate_user_turn(
        self, high_level_instruction: str, history: List[dict]
    ) -> Tuple[dict, bool, dict]:
        prompt = _assemble_prompt(high_level_instruction, self.persona, history)
        print("======= Simulator Prompt =======")
        print(prompt)
        self.model_name = 'gpt-4.1'
        resp = self.client.responses.create(
            model=self.model_name,
            input=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        print("======= Simulator Raw Response =======")
        print(resp)

        text = ""
        if getattr(resp, "output_text", None):
            text = resp.output_text
        elif getattr(resp, "output", None):
            chunks = []
            for item in resp.output:
                if getattr(item, "type", "") == "text":
                    chunks.append(getattr(item, "text", ""))
            if chunks:
                text = "\n".join(chunks)

        user_message = {"role": "user", "content": text}
        stop = TERMINATION_TOKEN in (text or "")
        trace = {"simulator": "openai", "prompt": prompt, "persona": self.persona_name}
        return user_message, stop, trace
