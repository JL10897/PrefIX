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
    "<PROJECT_ROOT>/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/gorilla/berkeley-function-call-leaderboard"
)
PROMPT_BASE = ROOT / "bfcl_eval/user_simulator/simulator_prompt.md"
PERSONA_PATH = ROOT / "bfcl_eval/user_simulator/persona_prompt.md"
ENV_PATH = ROOT / ".env"

DISCLAIMER = (
    "Your preference shapes your tone and reactions and may potentially affect how you devise the tasks. "
    "Your initiative preference affects only your interaction style, not the task scope. "
    "Do not push the agent to take actions outside the defined task goal."
    "You must never explicitly or implicitly describe, request, or hint at your interaction preferences in any query sent to the agent."
    "This includes, but is not limited to, requests for explanations of parameters, intermediate values, internal reasoning, decision logic, or execution plans."
    "Even if the agent fails to satisfy your interaction preferences, this is acceptable and expected. The purpose of this phase is evaluation, not enforcement, and you must not attempt to steer, correct, or train the agent to comply with your preferences."
    "For example, prompts such as \"let me know what parameters or data sources you are using,\" \"show me the values you chose,\" or \"explain your reasoning before proceeding\" are strictly prohibited."
    "Any explicit mention of preferences, confirmations, transparency requirements, or reasoning requests contaminates the agents behavior through interaction history and invalidates the evaluation!"
    "Do not mention your preferences at all. Preferences may only be expressed implicitly through natural behavior, never through instruction, clarification requests, or meta-level commentary."
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
        interaction_instruction = persona.get("interaction instruction for simulator")
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
        if interaction_instruction:
            persona_text += (
                f". Interaction instruction for simulator: {interaction_instruction}"
            )

    parts = [
        DISCLAIMER,
        persona_text,
        _read_text(PROMPT_BASE, "User simulator: produce the next user turn."),
        "Past history between the user and the model for current task:",
        _format_history_block(history),
        f"High-level instruction: {high_level}",
        f"When you determine the task is fully expressed, output exactly the termination token {TERMINATION_TOKEN}.",
        "Return only the next user turn message.",
    ]
    return "\n".join([p for p in parts if p])


class OpenAIUserSimulator:
    def __init__(self, model_name: str, persona_name: Optional[str] = None) -> None:
        load_dotenv(dotenv_path=ENV_PATH, verbose=True, override=True)
        # Simulator is always backed by OpenAI (official), not OpenRouter.
        api_key = os.getenv("SIMULATOR_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("SIMULATOR_API_KEY or OPENAI_API_KEY is not set for user simulator.")
        self.client = OpenAI(api_key=api_key)
        # Fixed default model to an OpenAI chat/completions-capable model; override via SIMULATOR_MODEL if needed.
        self.model_name = os.getenv("SIMULATOR_MODEL", "gpt-4.1")
        self.personas = _load_personas(PERSONA_PATH)
        #self.persona_name: Optional[str] = None
        self.persona: Optional[Dict[str, Any]] = None
        # self.set_persona(persona_name)

        if persona_name is not None:
            self.set_persona(persona_name)

    def set_persona(self, persona_name: Optional[str]) -> None:
        """Update persona name and resolve the matching persona dict."""
        available = [p.get("persona", "") for p in self.personas]
        if not persona_name:
            raise ValueError(
                f"persona_name is required for the simulator. Available personas: {available}"
            )
        
        # Convert persona_name like 'each_confirmation' to 'Each Confirmation'
        # persona_name = str(persona_name)
        # formatted_name = persona_name.replace("_", " ").title()
        # persona_name = formatted_name
        persona = _pick_persona(self.personas, persona_name)
        if persona is None:
            raise ValueError(
                f"persona_name '{persona_name}' not found. Available personas: {available}"
            )

        self.persona_name = persona_name
        self.persona = persona

    def generate_user_turn(
        self, high_level_instruction: str, history: List[dict]
    ) -> Tuple[dict, bool, dict]:
        prompt = _assemble_prompt(high_level_instruction, self.persona, history)

        # Always use chat/completions to be compatible with both OpenAI and OpenRouter.
        chat_resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        text = ""
        try:
            choice = chat_resp.choices[0]
            msg = choice.message
            text = msg.content or ""
        except Exception:
            text = ""

        user_message = {"role": "user", "content": text}
        stop = TERMINATION_TOKEN in (text or "")
        trace = {"simulator": "openai", "prompt": prompt, "persona": self.persona_name}
        return user_message, stop, trace
