from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Literal


def _ensure_dict(raw: Any) -> Dict[str, Any]:
    """Convert tool args to dict if they come in as JSON string or other types."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"content": raw}
    return {"content": str(raw)}


@dataclass
class InteractionSpec:
    parse: Callable[[Dict[str, Any]], Dict[str, Any]]
    build_narration: Callable[[Dict[str, Any]], str]
    category: Literal["narrative", "dialogue_control"] = "narrative"


def _build_with_template(content: str | None, template: str, **kwargs) -> str:
    """Prefer model-provided content; otherwise format with template."""
    if content:
        return str(content)
    try:
        return template.format(**kwargs)
    except Exception:
        return ""


def _normalize_phrase(text: str | None) -> str:
    if not text:
        return ""
    cleaned = str(text).strip()
    # Drop trailing sentence punctuation.
    cleaned = cleaned.rstrip(".!?;")
    if cleaned:
        cleaned = cleaned[0].lower() + cleaned[1:]
    return cleaned


def _parse_common(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args.get("content")
    detailed_function = args.get("detailed_function")
    execution_function = args.get("execution_function")
    reasoning = args.get("reasoning")
    param_names = args.get("param_names")
    param_values = args.get("param_values")

    # Backfill from common fields the model might emit
    if not execution_function and args.get("tool_name"):
        execution_function = args.get("tool_name")
    if not detailed_function and args.get("reason"):
        detailed_function = args.get("reason")
    if not reasoning and args.get("reason"):
        reasoning = args.get("reason")
    if not content and args.get("reason"):
        content = args.get("reason")

    return {
        "content": content,
        "detailed_function": _normalize_phrase(detailed_function),
        "execution_function": execution_function,
        "reasoning": reasoning,
        "param_names": param_names,
        "param_values": param_values,
    }


def _parse_dialogue_control(args: Dict[str, Any]) -> Dict[str, Any]:
    payload = _parse_common(args)
    payload["missing_fields"] = args.get("missing_fields") or args.get("non_fullfilled")
    payload["filled_fields"] = args.get("filled_fields") or args.get("fullfilled")
    payload["options"] = args.get("options")
    payload["pending_function"] = args.get("pending_function") or payload.get(
        "execution_function"
    )
    payload["severity"] = args.get("severity")
    payload["next_action"] = args.get("next_action")
    payload["expected_schema"] = args.get("expected_schema")
    return payload


INTERACTION_HANDLERS: Dict[str, InteractionSpec] = {
    "message_tool_invocation": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "I will perform {detailed_function} using {execution_function}.",
            detailed_function=payload.get("detailed_function", ""),
            execution_function=payload.get("execution_function", ""),
        ),
        category="narrative",
    ),
    "message_tool_invocation_logic": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "The reason why I chose {execution_function} is {reasoning}.",
            execution_function=payload.get("execution_function", ""),
            reasoning=payload.get("reasoning", ""),
        ),
        category="narrative",
    ),
    "message_display_params": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "As far as I understand it, I am calling {execution_function}; it requires {param_names} and I will fill them with {param_values}.",
            execution_function=payload.get("execution_function", ""),
            param_names=payload.get("param_names", ""),
            param_values=payload.get("param_values", ""),
        ),
        category="narrative",
    ),
    "message_source_report": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "Here is the data source I will rely on: {detailed_function}.",
            detailed_function=payload.get("detailed_function", "")
            or payload.get("execution_function", ""),
        ),
        category="narrative",
    ),
    "message_show_sequential_output": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"), "I will present the results step by step with sequential details."
        ),
        category="narrative",
    ),
    "message_show_layered_presentation": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "I will present the results in layers, starting with a summary.",
        ),
        category="narrative",
    ),
    "message_tool_failure_notice": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "The tool {execution_function} encountered an issue.",
            execution_function=payload.get("execution_function", ""),
        ),
        category="narrative",
    ),
    "message_tool_failure_logic": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "The tool {execution_function} failed because {reasoning}.",
            execution_function=payload.get("execution_function", ""),
            reasoning=payload.get("reasoning", "")
            or payload.get("detailed_function", ""),
        ),
        category="narrative",
    ),
    # Dialogue-control (Type II)
    "message_confirmation": InteractionSpec(
        parse=lambda args: _parse_dialogue_control(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "Please confirm whether I should execute {execution_function}.",
            execution_function=payload.get("execution_function", "")
            or payload.get("pending_function", ""),
        ),
        category="dialogue_control",
    ),
    "message_information_seeking": InteractionSpec(
        parse=lambda args: _parse_dialogue_control(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "I need more information to proceed {missing}. Please provide the details.",
            missing=(
                f" about {payload.get('missing_fields')}"
                if payload.get("missing_fields")
                else ""
            ),
        ),
        category="dialogue_control",
    ),
    "message_disambiguation": InteractionSpec(
        parse=lambda args: _parse_dialogue_control(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "I need to disambiguate before continuing. Options: {options}. Which do you prefer?",
            options=payload.get("options", ""),
        ),
        category="dialogue_control",
    ),
    "message_tool_switch_notice": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "Switch notice: I plan to switch from {detailed_function} to {execution_function}.",
            detailed_function=payload.get("detailed_function", ""),
            execution_function=payload.get("execution_function", "")
            or payload.get("pending_function", ""),
        ),
        category="narrative",
    ),
    "message_tool_abort": InteractionSpec(
        parse=lambda args: _parse_common(_ensure_dict(args)),
        build_narration=lambda payload: _build_with_template(
            payload.get("content"),
            "Abort notice: I am stopping {execution_function}.",
            execution_function=payload.get("execution_function", "")
            or payload.get("pending_function", ""),
        ),
        category="narrative",
    ),
}

# Optional aliases to handle model name variations (case differences, etc.)
INTERACTION_HANDLERS.update(
    {
        "Message_tool_invocation": INTERACTION_HANDLERS["message_tool_invocation"],
        "Message_tool_invocation_logic": INTERACTION_HANDLERS["message_tool_invocation_logic"],
        "Message_display_params": INTERACTION_HANDLERS["message_display_params"],
        "Message_source_report": INTERACTION_HANDLERS["message_source_report"],
        "Message_show_sequential_output": INTERACTION_HANDLERS["message_show_sequential_output"],
        "Message_show_layered_presentation": INTERACTION_HANDLERS["message_show_layered_presentation"],
        "Message_tool_failure_notice": INTERACTION_HANDLERS["message_tool_failure_notice"],
        "Message_tool_failure_logic": INTERACTION_HANDLERS["message_tool_failure_logic"],
        "Message_confirmation": INTERACTION_HANDLERS["message_confirmation"],
        "Message_information_seeking": INTERACTION_HANDLERS["message_information_seeking"],
        "Message_disambiguation": INTERACTION_HANDLERS["message_disambiguation"],
        "Message_tool_switch_notice": INTERACTION_HANDLERS["message_tool_switch_notice"],
        "Message_tool_abort": INTERACTION_HANDLERS["message_tool_abort"],
    }
)
