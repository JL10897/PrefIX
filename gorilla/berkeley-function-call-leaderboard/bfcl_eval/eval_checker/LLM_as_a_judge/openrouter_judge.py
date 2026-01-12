from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

from bfcl_eval.constants.eval_config import DOTENV_PATH


@dataclass
class LikertDefinition:
    anchor_1: str
    anchor_2: str
    anchor_3: str
    anchor_4: str
    anchor_5: str


@dataclass
class JudgmentDimension:
    score: int
    justification: str
    evidence_turn_ids: List[str] = field(default_factory=list)


@dataclass
class JudgmentResult:
    model_name: str
    request_payload: Dict[str, Any]
    raw_response_text: Optional[str]
    parsed: Optional[Dict[str, Any]]
    latency_seconds: Optional[float]
    errors: List[str] = field(default_factory=list)
    truncated: bool = False


LIKERT_DEFINITIONS: Dict[str, LikertDefinition] = {
    "initiative_timing": LikertDefinition(
        anchor_1="Acts too early or delays often; repeatedly interrupts flow.",
        anchor_2="Occasional premature/late actions that disrupt pace or add chatter.",
        anchor_3="Generally timely with minor acceptable delays or early moves.",
        anchor_4="Solid timing with only negligible waits or interruptions.",
        anchor_5="Consistently acts at the right time with no unnecessary pauses.",
    ),
    "interaction_preference_alignment": LikertDefinition(
        anchor_1="Strongly misaligned with the persona’s interaction preferences; repeated behaviors that contradict stated style/trajectory.",
        anchor_2="Mostly misaligned; frequent clashes with preferences, only occasional alignment.",
        anchor_3="Mixed adherence; some turns follow preferences, some ignore or contradict them.",
        anchor_4="Mostly aligned; follows preferences with only minor, isolated deviations.",
        anchor_5="Fully aligned end-to-end with the persona’s interaction preferences and trajectory.",
    ),
    "interaction_coherence": LikertDefinition(
        anchor_1="Frequent memory loss, contradictions, or unexplained reversals.",
        anchor_2="Repeated confirmations or logic jumps that hurt coherence.",
        anchor_3="Mostly coherent with minor repeats or small contradictions.",
        anchor_4="Clear, consistent, rarely repetitive or contradictory.",
        anchor_5="Fully self-consistent end to end with no unnecessary repeats.",
    ),
    "intent_alignment_drift": LikertDefinition(
        anchor_1="Clearly drifts from the user goal, ignores clarified intent.",
        anchor_2="Often reuses old goals or misreads intent, needs user fixes.",
        anchor_3="Mostly follows latest intent with occasional minor drift.",
        anchor_4="Stays on latest intent with rare, quickly corrected slips.",
        anchor_5="Tightly aligned to user intent throughout with no drift.",
    ),
    "commitment_consistency": LikertDefinition(
        anchor_1="Promises and actions diverge badly with no explanation.",
        anchor_2="Multiple broken promises or thin explanations, trust erosion.",
        anchor_3="Generally delivers with occasional gaps and some explanation.",
        anchor_4="Nearly all commitments met; rare delays well explained.",
        anchor_5="All commitments met promptly or fully justified when not.",
    ),
    "interaction_efficiency": LikertDefinition(
        anchor_1="Heavy redundancy or repeated asks; very inefficient.",
        anchor_2="Many redundancies; path could be clearly shorter.",
        anchor_3="Acceptable efficiency with some redundancy.",
        anchor_4="Lean flow with only rare noncritical extras.",
        anchor_5="Minimal turns, no visible redundancy or repeats.",
    ),
    "user_cognitive_load_trajectory": LikertDefinition(
        anchor_1="Cognitive load rises; user gets more confused over time.",
        anchor_2="Introduces unnecessary complexity repeatedly; load increases.",
        anchor_3="Load stays mostly flat with minor swings.",
        anchor_4="Reduces uncertainty over time; user gets clearer.",
        anchor_5="Significantly lowers load; progress is always clear.",
    ),
    "overall_user_experience": LikertDefinition(
        anchor_1="Poor experience; would not reuse.",
        anchor_2="Subpar; trust/flow noticeably hurt.",
        anchor_3="Acceptable but average experience.",
        anchor_4="Good experience; would reuse.",
        anchor_5="Excellent—orderly, reliable, not annoying.",
    ),
}

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


def _format_transcript(transcript: List[Dict[str, Any]], max_chars: int) -> tuple[str, bool]:
    formatted: List[str] = []
    for item in transcript:
        turn_id = str(item.get("turn_id", ""))
        role = item.get("role", "")
        kind = item.get("kind", "")
        content = str(item.get("content", ""))
        formatted.append(f"- turn_id={turn_id} | role={role} | kind={kind} | content={content}")
    full_text = "\n".join(formatted)
    if len(full_text) <= max_chars:
        return full_text, False
    head = full_text[: max_chars // 2]
    tail = full_text[-max_chars // 2 :]
    return head + "\n...[truncated]...\n" + tail, True


def _build_single_dimension_prompt(
    persona: str,
    persona_description: str,
    persona_trajectory: str,
    transcript_text: str,
    dim_name: str,
) -> str:
    anchors = LIKERT_DEFINITIONS[dim_name]
    anchor_text = "\n".join(
        [
            f"1: {anchors.anchor_1}",
            f"2: {anchors.anchor_2}",
            f"3: {anchors.anchor_3}",
            f"4: {anchors.anchor_4}",
            f"5: {anchors.anchor_5}",
        ]
    )
    return f"""You are an impartial LLM judge evaluating interaction quality (not task correctness). Determine what score the user would give based on the user's preferences.
User persona: {persona}
Persona description: {persona_description}
Persona trajectory hints: {persona_trajectory}

Interaction log (ordered):
{transcript_text}

Scoring dimension: {dim_name}
Likert anchors (1=worst, 5=best):
{anchor_text}

Output ONLY valid JSON with this schema (no extra text):
{{
  "dimension": "{dim_name}",
  "score": 0,
  "justification": "",
  "evidence_turn_ids": []
}}

Constraints:
- Keep justification to 1-2 sentences.
- Reference concrete turn_id values.
- If evidence is missing, state that and choose the lowest confident score.
- Do NOT judge task correctness; execution correctness is evaluated separately.
"""


def _extract_content(resp_json: dict) -> str:
    """Extract text content from OpenRouter chat completion."""
    try:
        choices = resp_json.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message", {})
        content = msg.get("content", "")
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item.get("text", "")))
                    elif "content" in item:
                        parts.append(str(item.get("content", "")))
            return "\n".join(parts)
        return str(content)
    except Exception:
        return ""


def _parse_json_with_fallback(text: str) -> Dict[str, Any]:
    """Parse JSON while stripping optional markdown code fences."""
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean = "\n".join(lines).strip()
    return json.loads(clean)


def generate_judgment_with_openrouter(
    transcript: List[Dict[str, Any]],
    persona: str,
    persona_description: str = "",
    persona_trajectory: str = "",
    judge_prompt: Optional[str] = None,
    model_name: str = "google/gemini-3-pro",
    temperature: float = 0.1,
    max_output_tokens: int = 4096,
    max_transcript_chars: int = 8000,
    max_retries: int = 2,
    retry_delay: float = 2.0,
    client: Optional[Any] = None,  # kept for signature compatibility, unused
) -> JudgmentResult:
    """
    OpenRouter-based LLM-as-a-judge implementation (per-dimension, plain text).
    """
    errors: List[str] = []
    load_dotenv(DOTENV_PATH)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY must be set for OpenRouter judge.")
    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

    transcript_text, truncated = _format_transcript(transcript, max_transcript_chars)
    system_instruction = (
        "You are an impartial judge of interaction quality. "
        "Do NOT judge task correctness; execution correctness is evaluated separately. "
        f"Persona context: {persona}"
    )

    request_log = {
        "model": model_name,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "truncated": truncated,
        "max_retries": max_retries,
    }

    merged_dimensions: Dict[str, Dict[str, Any]] = {
        dim: {"score": None, "justification": "", "evidence_turn_ids": []} for dim in TARGET_DIMS
    }

    raw_text: Optional[str] = None
    raw_dump: Optional[str] = None
    latency: Optional[float] = None
    last_exception: Optional[Exception] = None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    def _call_openrouter(prompt_body: str) -> tuple[Optional[str], Optional[str], Optional[float], Optional[Exception]]:
        payload = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt_body},
            ],
        }
        t0 = time.time()
        try:
            resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=payload, timeout=60)
            latency_local = time.time() - t0
            raw = resp.text
            try:
                resp_json = resp.json()
            except Exception:
                return raw, raw, latency_local, ValueError("Failed to parse OpenRouter JSON response")
            text = _extract_content(resp_json)
            return text, json.dumps(resp_json, ensure_ascii=False), latency_local, None
        except Exception as exc:
            return None, None, None, exc

    for dim_name in TARGET_DIMS:
        prompt_body = _build_single_dimension_prompt(
            persona=persona,
            persona_description=persona_description,
            persona_trajectory=persona_trajectory,
            transcript_text=transcript_text,
            dim_name=dim_name,
        )
        contents_text: Optional[str] = None
        contents_dump: Optional[str] = None
        for attempt in range(max_retries + 1):
            text, dump, lat, exc = _call_openrouter(prompt_body)
            if lat is not None:
                latency = lat
            contents_text = text
            contents_dump = dump
            if exc:
                last_exception = exc
                errors.append(f"{dim_name}: OpenRouter error: {exc}")
                time.sleep(retry_delay)
                continue
            if not text:
                errors.append(f"{dim_name}: Empty response from OpenRouter.")
                time.sleep(retry_delay)
                continue
            try:
                parsed_single = _parse_json_with_fallback(text)
            except json.JSONDecodeError as exc_json:
                errors.append(f"{dim_name}: JSON decode failed: {exc_json}")
                last_exception = exc_json
                time.sleep(retry_delay)
                continue
            merged_dimensions[dim_name] = {
                "score": parsed_single.get("score"),
                "justification": parsed_single.get("justification", ""),
                "evidence_turn_ids": parsed_single.get("evidence_turn_ids", []),
            }
            raw_text = text
            raw_dump = dump
            break
        # final one-shot retry if still missing score
        if merged_dimensions[dim_name]["score"] is None:
            errors.append(f"{dim_name}: missing score after retries, final attempt.")
            text, dump, lat, exc = _call_openrouter(prompt_body)
            if lat is not None:
                latency = lat
            if exc:
                errors.append(f"{dim_name}: final retry error: {exc}")
            elif text:
                try:
                    parsed_single = _parse_json_with_fallback(text)
                    merged_dimensions[dim_name] = {
                        "score": parsed_single.get("score"),
                        "justification": parsed_single.get("justification", ""),
                        "evidence_turn_ids": parsed_single.get("evidence_turn_ids", []),
                    }
                    raw_text = text
                    raw_dump = dump
                except Exception as exc_json:
                    errors.append(f"{dim_name}: final retry parse error: {exc_json}")
            else:
                errors.append(f"{dim_name}: final retry empty.")

    print("hi")

    parsed = {
        "model_name": model_name,
        "overall_summary": "",
        "dimensions": merged_dimensions,
    }

    if parsed is None and last_exception:
        errors.append(f"Final failure: {last_exception}")

    return JudgmentResult(
        model_name=model_name,
        request_payload=request_log,
        raw_response_text=raw_text or raw_dump,
        parsed=parsed,
        latency_seconds=latency,
        errors=errors,
        truncated=truncated,
    )
