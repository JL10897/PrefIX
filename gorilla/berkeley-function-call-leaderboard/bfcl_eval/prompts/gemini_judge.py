from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai.types import Content, GenerateContentConfig, Part, ThinkingConfig

from bfcl_eval.constants.eval_config import DOTENV_PATH

PROMPT_TEMPLATE_PATH = Path(__file__).with_name("prompt_template.md")


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


def load_prompt_template() -> str:
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _format_likert_definitions() -> str:
    lines: List[str] = []
    for key, definition in LIKERT_DEFINITIONS.items():
        lines.append(f"- {key}:")
        lines.append(f"  1: {definition.anchor_1}")
        lines.append(f"  2: {definition.anchor_2}")
        lines.append(f"  3: {definition.anchor_3}")
        lines.append(f"  4: {definition.anchor_4}")
        lines.append(f"  5: {definition.anchor_5}")
    return "\n".join(lines)


def _format_transcript(transcript: List[Dict[str, Any]], max_chars: int) -> Tuple[str, bool]:
    formatted_turns: List[str] = []
    for item in transcript:
        turn_id = str(item.get("turn_id", ""))
        role = item.get("role", "")
        kind = item.get("kind", "")
        content = str(item.get("content", ""))
        formatted_turns.append(f"- turn_id={turn_id} | role={role} | kind={kind} | content={content}")
    full_text = "\n".join(formatted_turns)
    if len(full_text) <= max_chars:
        return full_text, False
    head = full_text[: max_chars // 2]
    tail = full_text[-max_chars // 2 :]
    truncated = head + "\n...[truncated]...\n" + tail
    return truncated, True


def _render_prompt(
    persona: str,
    persona_description: str,
    persona_samples: str,
    transcript: List[Dict[str, Any]],
    judge_prompt: Optional[str],
    max_transcript_chars: int,
    model_name: str,
) -> Tuple[str, bool]:
    template = load_prompt_template()
    transcript_text, truncated = _format_transcript(transcript, max_transcript_chars)
    likert_text = _format_likert_definitions()
    output_schema = {
        "model_name": model_name,
        "overall_summary": "",
        "dimensions": {
            "initiative_timing": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "interaction_coherence": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "intent_alignment_drift": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "commitment_consistency": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "interaction_efficiency": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "user_cognitive_load_trajectory": {"score": 0, "justification": "", "evidence_turn_ids": []},
            "overall_user_experience": {"score": 0, "justification": "", "evidence_turn_ids": []},
        },
    }
    prompt_body = (
        template.replace("{{persona}}", persona)
        .replace("{{persona_description}}", persona_description)
        .replace("{{persona_samples}}", persona_samples)
        .replace("{{transcript}}", transcript_text)
        .replace("{{likert_definitions}}", likert_text)
        .replace("{{output_schema}}", json.dumps(output_schema, indent=2, ensure_ascii=False))
        .replace("{{judge_prompt}}", judge_prompt or "")
    )
    return prompt_body, truncated


def _extract_json_from_response(api_response: Any) -> str:
    """
    Extract JSON string from Gemini response.
    Handles both text parts and structured data (for response_mime_type=json).
    """
    if not api_response or not getattr(api_response, "candidates", None):
        return ""
    candidate = api_response.candidates[0]
    content = candidate.content
    if not content:
        return ""
    parts = content.parts or []
    texts: List[str] = []
    for part in parts:
        # Structured data (response_mime_type=application/json) comes in as inline_data
        if getattr(part, "inline_data", None):
            try:
                texts.append(part.inline_data.data.decode("utf-8"))
                continue
            except Exception:
                pass
        if getattr(part, "text", None):
            texts.append(part.text)
    return "\n".join(texts)


def _dump_response(api_response: Any) -> str:
    """Best-effort string dump for debugging Gemini responses."""
    try:
        if hasattr(api_response, "to_dict"):
            return json.dumps(api_response.to_dict(), ensure_ascii=False)
    except Exception:
        pass
    try:
        return repr(api_response)
    except Exception:
        return ""


def _validate_scores(parsed: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    dimensions = parsed.get("dimensions", {})
    for key in LIKERT_DEFINITIONS.keys():
        dim = dimensions.get(key)
        if dim is None:
            errors.append(f"Missing dimension: {key}")
            continue
        score = dim.get("score")
        if not isinstance(score, int) or not (1 <= score <= 5):
            errors.append(f"Invalid score for {key}: {score}")
        if "justification" not in dim:
            errors.append(f"Missing justification for {key}")
        if "evidence_turn_ids" not in dim:
            errors.append(f"Missing evidence_turn_ids for {key}")
    return errors


def generate_judgment_with_gemini(
    transcript: List[Dict[str, Any]],
    persona: str,
    persona_description: str = "",
    persona_samples: Optional[List[str]] = None,
    judge_prompt: Optional[str] = None,
    model_name: str = "gemini-3-pro-preview",
    temperature: float = 0.1,
    max_output_tokens: int = 1024,
    max_transcript_chars: int = 8000,
    max_retries: int = 0,
    retry_delay: float = 2.0,
    client: Optional[genai.Client] = None,
) -> JudgmentResult:
    """
    Gemini 3 Pro-based LLM-as-a-judge implementation.
    """
    errors: List[str] = []
    # Load .env to populate GOOGLE_API_KEY if available.
    load_dotenv(DOTENV_PATH)
    prompt_body, truncated = _render_prompt(
        persona=persona,
        persona_description=persona_description or "N/A",
        persona_samples="\n".join([f"- {s}" for s in persona_samples]) if persona_samples else "N/A",
        transcript=transcript,
        judge_prompt=judge_prompt,
        max_transcript_chars=max_transcript_chars,
        model_name=model_name,
    )
    system_instruction = (
        "You are an impartial judge of interaction quality. "
        "Do NOT judge task correctness; execution correctness is evaluated separately. "
        f"Persona context: {persona}"
    )
    print(
        "[GeminiJudge] Init client and request:",
        json.dumps(
            {
                "model_name": model_name,
                "temperature": temperature,
                "max_output_tokens": max_output_tokens,
                "max_transcript_chars": max_transcript_chars,
                "truncated": truncated,
            },
            ensure_ascii=False,
        ),
    )

    if client is None:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY environment variable must be set for Gemini judge.")
        client = genai.Client(api_key=api_key)

    contents = [Content(role="user", parts=[Part(text=prompt_body)])]
    print("[GeminiJudge] Prepared prompt for Gemini (not printing full body to save space).")

    request_log = {
        "model": model_name,
        "system_instruction": system_instruction,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
        "truncated": truncated,
        "max_retries": max_retries,
    }

    raw_text: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    latency: Optional[float] = None
    last_exception: Optional[Exception] = None
    raw_dump: Optional[str] = None

    for attempt in range(max_retries + 1):
        start = time.time()
        try:
            config = GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                response_mime_type="application/json",
                thinking_config=ThinkingConfig(include_thoughts=False),
            )
            print(f"[GeminiJudge] Attempt {attempt+1} with response_mime_type=application/json")
            response = client.models.generate_content(model=model_name, contents=contents, config=config)
            latency = time.time() - start
            raw_dump = _dump_response(response)
            raw_text = _extract_json_from_response(response)
            if not raw_text:
                print("[GeminiJudge] Empty text extracted; raw dump (first 2000 chars):")
                print((raw_dump or "")[:2000])
            else:
                print("[GeminiJudge] Raw text received (first 1000 chars):")
                print(raw_text)
            if not raw_text:
                errors.append("Empty response from Gemini.")
                continue
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                errors.append(f"JSON decode failed: {exc}")
                last_exception = exc
                time.sleep(retry_delay)
                continue
            errors.extend(_validate_scores(parsed))
            break
        except (genai_errors.ClientError, genai_errors.ServerError) as exc:
            last_exception = exc
            errors.append(f"Gemini API error: {exc}")
            time.sleep(retry_delay)
        except Exception as exc:  # pylint: disable=broad-except
            last_exception = exc
            errors.append(f"Unexpected error: {exc}")
            time.sleep(retry_delay)

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
