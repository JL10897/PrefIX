import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from bfcl_eval.constants.category_mapping import (
    MULTI_TURN_FUNC_DOC_FILE_MAPPING,
    VERSION_PREFIX,
)
from bfcl_eval.constants.default_prompts import (
    DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC,
    DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_PROMPTING,
    MAXIMUM_STEP_LIMIT,
)
from bfcl_eval.constants.eval_config import MULTI_TURN_FUNC_DOC_PATH
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import (
    STATELESS_CLASSES,
    execute_multi_turn_func_call,
    is_empty_execute_response,
)
from bfcl_eval.model_handler.interaction_handlers import INTERACTION_HANDLERS
from bfcl_eval.model_handler.model_style import ModelStyle
from bfcl_eval.prompts.loader import load_prompt_bundle
from bfcl_eval.utils import load_file, make_json_serializable, sort_key
from bfcl_eval.user_simulator.user_simulator_openai import OpenAIUserSimulator
from overrides import final


class BaseHandler:
    model_name: str
    model_style: ModelStyle

    def __init__(self, model_name, temperature) -> None:
        """Initialize shared handler metadata such as model name and temperature."""
        self.model_name = model_name
        # Replace the slash with underscore to avoid creating subdirectories
        # Replace the dash and dot with underscore for valid variable name
        self.model_name_underline_replaced = (
            model_name.replace("/", "_").replace("-", "_").replace(".", "_")
        )
        self.temperature = temperature
        self.is_fc_model = False  # Whether the model is a function calling model
        # Default user simulator; can be swapped via init config.
        self.user_simulator = OpenAIUserSimulator(model_name="o4-mini-2025-04-16")
        # Optional persona name to pass to OpenAIUserSimulator.
        self.simulator_persona = None
        # Optional suffix to select interaction_history_<suffix>.txt.
        self.interaction_history_suffix: str | None = None
        # Toggle for prepending prompts/interaction_history.txt.
        self.include_interaction_history = True
        # Dialogue-control state
        self.dialogue_state = "RUNNING"  # RUNNING | AWAITING_USER
        self.pending_interaction: dict | None = None

    @staticmethod
    def _normalize_simulator_utterance(text: str) -> str:
        """
        Extremely lightweight normalization for simulator utterances.
        """
        normalized = str(text or "").lower().strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.strip(".,!?;:")
        return normalized

    @staticmethod
    def _seed_simulator_repeat_counter(history: list[dict]) -> dict[str, int]:
        counter: dict[str, int] = {}
        for msg in history or []:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            normalized = BaseHandler._normalize_simulator_utterance(msg.get("content", ""))
            if not normalized:
                continue
            counter[normalized] = counter.get(normalized, 0) + 1
        return counter

    @staticmethod
    def _increment_simulator_repeat_counter(inference_data: dict, normalized: str) -> int:
        counter = inference_data.setdefault("simulator_repeat_counter", {})
        counter[normalized] = counter.get(normalized, 0) + 1
        return counter[normalized]

    @staticmethod
    def _history_line_count(history: list[dict]) -> int:
        return len(history or [])

    def _persist_history_line(self, history_persist_path: Path | None, msg: dict) -> None:
        if not history_persist_path:
            return
        with history_persist_path.open("a", encoding="utf8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    @staticmethod
    def _collect_functions_from_involved_classes(test_entry: dict) -> list:
        """
        Build the tool list by aggregating all func_doc entries whose names fall
        under the namespaces specified in `involved_classes`. Falls back to the
        existing test_entry["function"] if no additional docs are found.
        """
        involved_classes: list[str] = test_entry.get("involved_classes", []) or []
        combined: dict[str, dict] = {}
        existing_functions = test_entry.get("function", []) or []

        # Preserve any functions already attached to the entry (including holdouts re-added later)
        for func in existing_functions:
            if isinstance(func, dict) and "name" in func:
                combined[str(func["name"])] = func

        missed_names: set[str] = set()
        for names in test_entry.get("missed_function", {}).values():
            if isinstance(names, list):
                for item in names:
                    if isinstance(item, dict) and "name" in item:
                        missed_names.add(str(item["name"]))
                    elif isinstance(item, str):
                        missed_names.add(item)

        for class_name in involved_classes:
            file_name = MULTI_TURN_FUNC_DOC_FILE_MAPPING.get(class_name)
            if not file_name:
                continue
            func_doc_path = MULTI_TURN_FUNC_DOC_PATH / file_name
            if not func_doc_path.exists():
                continue
            func_doc = load_file(func_doc_path)
            if not isinstance(func_doc, list):
                continue
            for func in func_doc:
                if not isinstance(func, dict):
                    continue
                func_name = str(func.get("name", ""))
                if not func_name.startswith(f"{class_name}."):
                    continue
                # Respect holdout by skipping missed names unless they were explicitly re-added.
                if func_name in missed_names and func_name not in combined:
                    continue
                combined.setdefault(func_name, func)

        # Always append interaction tools.
        interaction_doc_path = MULTI_TURN_FUNC_DOC_PATH / "interaction.json"
        if interaction_doc_path.exists():
            interaction_funcs = load_file(interaction_doc_path)
            if isinstance(interaction_funcs, list):
                for func in interaction_funcs:
                    if not isinstance(func, dict) or "name" not in func:
                        continue
                    combined.setdefault(str(func["name"]), func)

        return list(combined.values())

    @staticmethod
    def _clean_user_for_history(message: dict) -> dict:
        content = ""
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = str(message)
        return {"role": "user", "content": content}

    @staticmethod
    def clean_assistant_for_history(raw_message) -> dict:
        """
        Remove tool/function metadata and keep only assistant natural language text for history.
        """
        def _drop_reasoning_fields(obj):
            if isinstance(obj, dict):
                return {
                    k: _drop_reasoning_fields(v)
                    for k, v in obj.items()
                    if k not in ("reasoning", "reasoning_details")
                }
            if isinstance(obj, list):
                return [_drop_reasoning_fields(item) for item in obj]
            return obj

        # Handle Google Gemini Content-like objects (role + parts)
        if hasattr(raw_message, "parts") and hasattr(raw_message, "role"):
            parts = getattr(raw_message, "parts", []) or []
            text_chunks: list[str] = []
            for part in parts:
                if hasattr(part, "text") and part.text:
                    text_chunks.append(str(part.text))
            content = "\n".join([c for c in text_chunks if c])
            return {
                "role": getattr(raw_message, "role", "assistant") or "assistant",
                "content": content,
            }

        if isinstance(raw_message, dict):
            role = raw_message.get("role", "assistant")
            content = raw_message.get("content", "")
            cleaned: dict[str, Any] = {"role": role}
            if isinstance(content, list):
                text_chunks = []
                for item in content:
                    if isinstance(item, dict):
                        if "text" in item:
                            text_chunks.append(str(item.get("text", "")))
                        elif "content" in item:
                            text_chunks.append(str(item.get("content", "")))
                    elif isinstance(item, str):
                        text_chunks.append(item)
                content = "\n".join([c for c in text_chunks if c])
            if isinstance(content, dict):
                content = content.get("text", "") or content.get("content", "")
            if not isinstance(content, str):
                content = str(content)
            if not content:
                # If no textual content could be extracted, serialize the message for visibility.
                content = json.dumps(
                    _drop_reasoning_fields(make_json_serializable(raw_message)),
                    ensure_ascii=False,
                )
            cleaned["content"] = content
            if "tool_calls" in raw_message:
                serialized_calls = make_json_serializable(raw_message.get("tool_calls"))
                cleaned["tool_calls"] = serialized_calls
            if "function_call" in raw_message:
                cleaned["function_call"] = make_json_serializable(
                    raw_message.get("function_call")
                )
            if "call_id" in raw_message:
                cleaned["call_id"] = raw_message.get("call_id")
            return cleaned

        # Try rich SDK objects (e.g., OpenAI/Anthropic responses) before falling back to a truncated repr.
        for attr in ("model_dump", "dict", "to_dict"):
            if hasattr(raw_message, attr):
                try:
                    candidate = getattr(raw_message, attr)()
                    if candidate is not raw_message:
                        return BaseHandler.clean_assistant_for_history(candidate)
                except Exception:
                    pass

        if hasattr(raw_message, "tool_calls"):
            role = getattr(raw_message, "role", "assistant") or "assistant"
            content = getattr(raw_message, "content", "") or ""
            if not isinstance(content, str):
                content = str(content)
            reasoning = getattr(raw_message, "reasoning", None)
            reasoning_details = getattr(raw_message, "reasoning_details", None)
            serialized_calls = make_json_serializable(getattr(raw_message, "tool_calls"))
            if not content:
                content = json.dumps(
                    {"tool_calls": serialized_calls},
                    ensure_ascii=False,
                )
            return {
                "role": role,
                "content": content,
                "tool_calls": serialized_calls,
            }

        text_like = getattr(raw_message, "text", None) or getattr(raw_message, "content", None)
        if text_like:
            return BaseHandler.clean_assistant_for_history(
                {
                    "role": getattr(raw_message, "role", "assistant") or "assistant",
                    "content": text_like,
                }
            )

        # Final fallback: serialize safely to preserve structure instead of using str().
        serialized = json.dumps(make_json_serializable(raw_message), ensure_ascii=False)
        # print("passed")
        return {"role": "assistant", "content": serialized}

    @staticmethod
    def _normalize_tag(tag: str | None) -> str:
        """
        Normalize persona/history suffix to a filesystem-friendly folder name.
        """
        if not tag:
            return "default"
        cleaned = str(tag).strip().lower().replace(" ", "_")
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in ("_", "-"))
        return cleaned or "default"

    @staticmethod
    def _tool_result_history_entry(tool_call: any, execution_result: any, call_id: str | None = None) -> dict:
        tool_name = ""
        if isinstance(tool_call, str):
            tool_name = tool_call.split("(", 1)[0]
            if "." in tool_name:
                tool_name = tool_name.split(".")[-1]
        tool_name = tool_name or "tool_call"
        entry = {"role": "tool", "name": tool_name, "content": str(execution_result)}
        if call_id:
            entry["call_id"] = call_id
        return entry

    @staticmethod
    def _validate_prompt_requirements(
        inference_data: dict, require_history: bool = True
    ) -> None:
        """
        Ensure required prompt components exist before querying the LLM client.
        Raises ValueError with a concise list of missing items.
        """
        missing: list[str] = []
        if not inference_data.get("system_prompts"):
            missing.append("system_prompts")
        if not inference_data.get("interaction_instructions"):
            missing.append("interaction_instructions")
        if require_history and not inference_data.get("interaction_history"):
            missing.append("interaction_history")
        if missing:
            raise ValueError(
                f"Missing required prompt components before LLM call: {', '.join(missing)}"
            )

    @staticmethod
    def _collect_prepended_prompts(
        inference_data: dict, default_role: str = "system"
    ) -> list[dict]:
        """
        Prepare system/interaction prompts and history as message dicts to prepend once per conversation.
        """
        messages: list[dict] = []
        for prompt in inference_data.get("system_prompts", []) or []:
            messages.append({"role": default_role, "content": str(prompt)})
        for prompt in inference_data.get("interaction_instructions", []) or []:
            messages.append({"role": default_role, "content": str(prompt)})
        for history_entry in inference_data.get("interaction_history", []) or []:
            if isinstance(history_entry, dict) and history_entry.get("role"):
                messages.append(history_entry)
            elif isinstance(history_entry, str):
                messages.append({"role": default_role, "content": history_entry})
        return messages

    def _format_interaction_outputs_for_api(self, messages: list[dict]) -> list[dict]:
        """
        Hook for provider-specific formatting of synthetic interaction tool outputs.
        Default is no-op; override in API-specific handlers.
        """
        return messages

    @staticmethod
    def _extract_interaction_events(
        model_responses: any,
        tool_call_ids: list[str] | None = None,
        tool_call_signature_map: dict[str, str | None] | None = None,
        tool_thought_signatures: list[str] | None = None,
    ) -> tuple[list[str], list[dict], any, list[str], list[dict], list[str]]:
        """
        Split interaction tools from task tools, build narration strings, and capture dialogue-control events.

        Returns:
            narrations: list of narration strings (Type I + Type II) to show user
            dialogue_controls: list of dict{name, payload, narration, call_id}
            filtered_responses: model_responses with interaction tools removed
            filtered_tool_call_ids: tool_call_ids with interaction tools removed
            interaction_tool_outputs: synthetic tool output messages for interaction tools (to satisfy API threading)
            filtered_tool_thought_signatures: tool_thought_signatures with interaction tools removed
        """
        narrations: list[str] = []
        dialogue_controls: list[dict] = []
        interaction_tool_outputs: list[dict] = []
        if not isinstance(model_responses, list):
            return (
                narrations,
                dialogue_controls,
                model_responses,
                tool_call_ids or [],
                interaction_tool_outputs,
                tool_thought_signatures or [],
            )

        signature_map = tool_call_signature_map or {}
        if not signature_map and tool_call_ids and tool_thought_signatures:
            signature_map = {
                cid: tool_thought_signatures[idx]
                for idx, cid in enumerate(tool_call_ids)
                if cid is not None and idx < len(tool_thought_signatures)
            }

        filtered: list = []
        filtered_ids: list[str] = []
        filtered_thought_signatures: list[str] = []
        for idx, item in enumerate(model_responses):
            tool_name = None
            tool_args = None
            if isinstance(item, dict) and len(item) == 1:
                tool_name = list(item.keys())[0]
                tool_args = item[tool_name]
            if tool_name:
                handler_key = tool_name if tool_name in INTERACTION_HANDLERS else tool_name.lower()
            else:
                handler_key = None
            if handler_key and handler_key in INTERACTION_HANDLERS:
                spec = INTERACTION_HANDLERS[handler_key]
                payload = spec.parse(tool_args)
                narration = spec.build_narration(payload)
                if narration:
                    narrations.append(str(narration))
                call_id = tool_call_ids[idx] if tool_call_ids and idx < len(tool_call_ids) else None
                thought_signature = signature_map.get(call_id)
                if spec.category == "dialogue_control":
                    dialogue_controls.append(
                        {
                            "name": handler_key,
                            "payload": payload,
                            "narration": narration,
                            "call_id": call_id,
                        }
                )
                # Keep API happy by emitting synthetic outputs for interaction tools
                if call_id or thought_signature:
                    out_msg = {
                        "type": "function_call_output",
                        "class_name": "interaction",
                        "output": narration or "acknowledged.",
                    }
                    if call_id:
                        out_msg["call_id"] = call_id
                    if thought_signature:
                        out_msg["thought_signature"] = thought_signature
                    interaction_tool_outputs.append(out_msg)
                continue
            filtered.append(item)
            if tool_call_ids and idx < len(tool_call_ids):
                filtered_ids.append(tool_call_ids[idx])
            if tool_thought_signatures and idx < len(tool_thought_signatures):
                filtered_thought_signatures.append(tool_thought_signatures[idx])

        return (
            narrations,
            dialogue_controls,
            filtered,
            filtered_ids,
            interaction_tool_outputs,
            filtered_thought_signatures,
        )

    @staticmethod
    def _build_resolve_messages(pending_interaction: dict, user_reply: list[dict]) -> list[dict]:
        """
        Construct a resolver prompt that asks the model to output ONLY structured JSON to resolve a pending Type II.
        """
        pending_name = str(pending_interaction.get("name", "")).lower()
        payload = pending_interaction.get("payload", {}) or {}
        system_text = (
            "You are a resolution assistant. "
            "Given a pending dialogue-control interaction and the latest user reply, "
            "output ONLY a JSON object with resolution details. "
            "Do NOT call tools. Do NOT output natural language."
        )
        instructions = {
            "pending_interaction": pending_name,
            "expected_schema_hint": pending_interaction.get("payload", {}).get("expected_schema"),
            "payload": payload,
        }
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": json.dumps(instructions, ensure_ascii=False)},
            {"role": "user", "content": json.dumps({"user_reply": user_reply}, ensure_ascii=False)},
        ]

    def _query_resolve(self, messages: list[dict]) -> dict | str | None:
        """
        Default resolver: call the same model with an empty tool list and return raw output.
        API-specific handlers can override for tighter control.
        """
        try:
            payload = {"message": messages, "tools": []}
            api_response = self._query_FC(payload)
            parsed = self._parse_query_response_FC(api_response)
            candidate = parsed.get("model_responses")
            if isinstance(candidate, list) and candidate:
                return candidate[0]
            return candidate
        except Exception:
            return None

    def _run_resolve_client(self, resolve_request: dict) -> dict:
        """
        Invoke a lightweight resolution client (separate from main FC query) to parse user replies.
        """
        pending_interaction = resolve_request.get("pending_interaction") or {}
        user_reply = resolve_request.get("user_reply") or []
        resolve_messages = self._build_resolve_messages(pending_interaction, user_reply)
        try:
            raw = self._query_resolve(resolve_messages)
            if raw is None:
                raise ValueError("No resolver implemented")
            if isinstance(raw, str):
                return json.loads(raw)
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        # Fallback: REJECT to stay safe
        return {"resolution": "REJECT"}

    # def _run_resolve_client(self, resolve_request: dict) -> dict:
    #     """
    #     Invoke a lightweight resolution client to parse user replies for pending dialogue-control interactions.
    #     Default fallback: reject/keep awaiting if not overridden.
    #     """
    #     return resolve_request.get("fallback_resolution", {"resolution": "REJECT"})

    def inference(self, test_entry: dict, include_input_log: bool, exclude_state_log: bool):
        """
        Dispatch the evaluation request to the appropriate inference routine.

        Multi-turn and single-turn executions are separated, and within each branch we
        further dispatch to the FC (tool) implementation or the prompting-only variant
        depending on the handler configuration.
        """
        # This method is used to retrive model response for each model.

        # FC (function-calling) model path
        # TODO: Let all models have the is_fc_model attribute and remove the "FC" check
        if "FC" in self.model_name or self.is_fc_model:
            if "multi_turn" in test_entry["id"]:
                return self.inference_multi_turn_FC(
                    test_entry, include_input_log, exclude_state_log
                )
            else:
                return self.inference_single_turn_FC(test_entry, include_input_log)
        # Prompting-only model path
        else:
            if "multi_turn" in test_entry["id"]:
                return self.inference_multi_turn_prompting(
                    test_entry, include_input_log, exclude_state_log
                )
            else:
                return self.inference_single_turn_prompting(test_entry, include_input_log)

    @final
    def inference_multi_turn_FC(
        self, test_entry: dict, include_input_log: bool, exclude_state_log: bool
    ) -> tuple[list[list], dict]:
        """
        Run a full multi-turn interaction for FC-capable models.

        This orchestrates user turns, repeatedly queries the model, executes decoded
        tool calls, logs intermediate state, and returns the raw responses alongside
        metadata for downstream evaluation.
        """
        initial_config: dict = test_entry["initial_config"]
        involved_classes: list = test_entry["involved_classes"]
        test_entry_id: str = test_entry["id"]
        test_category: str = test_entry_id.rsplit("_", 1)[0]

        # This is only for the miss function category
        # A mapping from turn index to function to holdout
        holdout_function: dict[int, list] = test_entry.get("missed_function", {})

        total_input_token_count: list[list[float]] = []
        total_output_token_count: list[list[float]] = []
        total_latency: list[list[float]] = []
        all_model_response: list[list] = (
            []
        )  # The model response that will be used for later evaluation
        all_inference_log: list[list[dict]] = (
            []
        )  # The debugging log for human to understand
        force_quit = False  # Whether the model has been forced to quit. If True, this whole entry will be failed.
        termination_reason: str | None = None
        termination_detail: str | None = None
        HISTORY_LINE_LIMIT = 180

        all_reasoning_content: list[list] = []
        # Execute no function call, but just to get a reference to all the instances to get the initial state for logging purpose
        if not exclude_state_log:
            _, involved_instances = execute_multi_turn_func_call(
                [],
                initial_config,
                involved_classes,
                self.model_name_underline_replaced,
                test_entry_id,
                long_context=(
                    "long_context" in test_category or "composite" in test_category
                ),
                is_evaL_run=False,
            )
            state_log = []
            for class_name, class_instance in involved_instances.items():
                if class_name in STATELESS_CLASSES:
                    continue
                # Avoid modification in future turns
                class_instance = deepcopy(class_instance)
                state_log.append(
                    {
                        "role": "state_info",
                        "class_name": class_name,
                        "content": {
                            key: value
                            for key, value in vars(class_instance).items()
                            if not key.startswith("_")
                        },
                    }
                )
            all_inference_log.append(state_log)

        inference_data: dict = {}
        inference_data = self._pre_query_processing_FC(inference_data, test_entry)
        test_entry["function"] = self._collect_functions_from_involved_classes(test_entry)
        inference_data = self._compile_tools(inference_data, test_entry)
        prompt_bundle = self.build_prompt_bundle_FC(test_entry)
        if not getattr(self, "include_interaction_history", True):
            prompt_bundle = {**prompt_bundle, "interaction_history": []}
        inference_data["system_prompts"] = prompt_bundle.get("system_prompts", [])
        inference_data["interaction_instructions"] = prompt_bundle.get(
            "interaction_instructions", []
        )
        inference_data["interaction_history"] = prompt_bundle.get("interaction_history", [])
        self._validate_prompt_requirements(
            inference_data, require_history=getattr(self, "include_interaction_history", True)
        )
        inference_data.setdefault("dialogue_state", "RUNNING")
        inference_data.setdefault("pending_interaction", None)

        # 如果是 OpenAIUserSimulator，确保 persona 设置
        if isinstance(self.user_simulator, OpenAIUserSimulator):
            persona_name = getattr(self, "simulator_persona", None)
            self.user_simulator.set_persona(persona_name)

        # 历史存储初始化（持久化）
        history_root = Path(
            "<PROJECT_ROOT>/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/gorilla/berkeley-function-call-leaderboard/bfcl_eval/user_simulator/history"
        )
        persona_folder = self._normalize_tag(
            getattr(self, "interaction_history_suffix", None)
            or getattr(self, "simulator_persona", None)
        )
        personalization_state = (
            "personalization" if getattr(self, "include_interaction_history", True) else "no_personalization"
        )
        history_dir = (
            history_root
            / self.model_name_underline_replaced
            / personalization_state
            / persona_folder
        )
        history_dir.mkdir(parents=True, exist_ok=True)
        history_persist_path = history_dir / f"{test_entry_id}.json"

        inference_data["history"] = []
        history_created = False
        if history_persist_path.exists():
            try:
                with history_persist_path.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if isinstance(obj, dict):
                            inference_data["history"].append(obj)
                        elif isinstance(obj, list):
                            inference_data["history"].extend(
                                [item for item in obj if isinstance(item, dict)]
                            )
                    if not inference_data["history"]:
                        try:
                            persisted = json.loads(history_persist_path.read_text())
                            if isinstance(persisted, list):
                                inference_data["history"] = [
                                    item for item in persisted if isinstance(item, dict)
                                ]
                            elif isinstance(persisted, dict):
                                inference_data["history"] = [persisted]
                        except json.JSONDecodeError:
                            pass
            except FileNotFoundError:
                inference_data["history"] = []
        else:
            history_persist_path.touch()
            history_created = True
        inference_data["simulator_repeat_counter"] = self._seed_simulator_repeat_counter(
            inference_data.get("history", [])
        )

        simulator_turns = 0
        turn_idx = 0
        while True:
            # 检查历史中是否已有终止
            last_user = None
            for msg in reversed(inference_data.get("history", [])):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    last_user = msg
                    break
            if last_user:
                content = str(last_user.get("content", "") or "").strip()
                if "<END_SIMULATION>" in content:
                    break

            # Simulator 
            user_message, sim_stop, simulator_trace = self.user_simulator.generate_user_turn(
                test_entry.get("high_level_instruction", ""),
                inference_data.get("history", []),
            )
            simulator_turns += 1
            user_content = ""
            if isinstance(user_message, dict):
                user_content = user_message.get("content", "")
            else:
                user_content = str(user_message)
            current_turn_message = [{"role": "user", "content": user_content}]

            is_holdout_turn = str(turn_idx) in holdout_function
            if is_holdout_turn:
                # Miss-function category: re-add the held-out tools at this turn
                test_entry["function"].extend(holdout_function[str(turn_idx)])
                # Since we have added new functions, we need to recompile the tools
                test_entry["function"] = self._collect_functions_from_involved_classes(
                    test_entry
                )
                inference_data = self._compile_tools(inference_data, test_entry)
                # Ignore simulator output and use default holdout prompt
                current_turn_message = [
                    {
                        "role": "user",
                        "content": DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC,
                    }
                ]
            current_turn_response = []  # All responses (per step) for this turn
            current_turn_inference_log: list[dict] = {
                "begin_of_turn_query": current_turn_message
            }
            if simulator_trace:
                current_turn_inference_log["simulator_trace"] = simulator_trace
            current_turn_input_token_count: list[float] = []
            current_turn_output_token_count: list[float] = []
            current_turn_latency: list[float] = []
            current_turn_reasoning_content = []
            if turn_idx == 0:
                inference_data = self.add_first_turn_message_FC(
                    inference_data, current_turn_message
                )
            else:
                inference_data = self._add_next_turn_user_message_FC(
                    inference_data, current_turn_message
                )

            # 更新统一 history 并持久化
            # user_history_messages = [
            #     self._clean_user_for_history(msg) for msg in current_turn_message
            # ]
            user_history_messages = [msg for msg in current_turn_message]
            inference_data["history"].extend(user_history_messages)
            for msg in user_history_messages:
                self._persist_history_line(history_persist_path, msg)

            termination_note = None
            if not is_holdout_turn:
                normalized = self._normalize_simulator_utterance(user_content)
                if normalized:
                    repeat_count = self._increment_simulator_repeat_counter(
                        inference_data, normalized
                    )
                    if repeat_count >= 3 and termination_reason is None:
                        termination_reason = "simulator_repeat_limit"
                        termination_note = {
                            "role": "handler_log",
                            "content": "Simulator self-terminated after repeating the same utterance 3 times.",
                            "normalized_utterance": normalized,
                            "repeat_count": repeat_count,
                        }

            history_line_count = self._history_line_count(inference_data.get("history", []))
            if (
                termination_reason is None
                and history_line_count > HISTORY_LINE_LIMIT
            ):
                termination_reason = "history_line_limit"
                termination_note = {
                    "role": "handler_log",
                    "content": f"History exceeded {HISTORY_LINE_LIMIT} lines; terminating without further API calls.",
                    "history_line_count": history_line_count,
                }

            if termination_note:
                current_turn_inference_log.setdefault("termination", []).append(termination_note)
                termination_detail = termination_note.get("content")
                all_model_response.append([])
                all_inference_log.append([current_turn_inference_log])
                total_input_token_count.append([])
                total_output_token_count.append([])
                total_latency.append([])
                all_reasoning_content.append([])
                force_quit = True
                break

            # If the simulator has signaled termination, end the conversation without querying the agent.
            if "<END_SIMULATION>" in (user_content or "") or sim_stop:
                break

            # Resolve pending dialogue-control if we were awaiting user
            if inference_data.get("dialogue_state") == "AWAITING_USER":
                def _run_pending_type3(pending: dict):
                    pending_calls = pending.get("pending_type3_calls") or []
                    pending_thought_signatures = pending.get("pending_type3_thought_signatures") or []
                    if not pending_calls:
                        return
                    try:
                        decoded_pending = self.decode_execute(pending_calls)
                        if not decoded_pending or is_empty_execute_response(decoded_pending):
                            return
                        execution_results, involved_instances_inner = execute_multi_turn_func_call(
                        decoded_pending,
                        initial_config,
                        involved_classes,
                        self.model_name_underline_replaced,
                        test_entry_id,
                        long_context=(
                            "long_context" in test_category or "composite" in test_category
                        ),
                        is_evaL_run=False,
                    )
                        # Add execution results to chat message/history for next model turn
                        inference_data_updated = self._add_execution_results_FC(
                            inference_data,
                            execution_results,
                            {
                                "tool_call_ids": pending.get("pending_type3_call_ids", []),
                                "tool_thought_signatures": pending_thought_signatures,
                            },
                        )
                        if inference_data_updated:
                            inference_data.update(inference_data_updated)
                        # Add execution results to history
                        tool_history_entries = []
                        call_ids_exec = pending.get("pending_type3_call_ids", []) or []
                        for idx, (decoded_call, execution_result) in enumerate(
                            zip(decoded_pending, execution_results)
                        ):
                            call_id = call_ids_exec[idx] if idx < len(call_ids_exec) else None
                            tool_history_entries.append(
                                self._tool_result_history_entry(decoded_call, execution_result, call_id)
                            )
                        if not tool_history_entries and execution_results:
                            tool_history_entries = [
                                {"role": "tool", "name": "tool_call", "content": str(result)}
                                for result in execution_results
                            ]
                        for entry in tool_history_entries:
                            inference_data.setdefault("history", []).append(entry)
                            self._persist_history_line(history_persist_path, entry)
                        for execution_result in execution_results:
                            current_turn_inference_log.setdefault("resolve_execution", []).append(
                                {"role": "tool", "content": execution_result}
                            )
                    except Exception as e:
                        current_turn_inference_log.setdefault("resolve_execution", []).append(
                            {"role": "handler_log", "content": "Error executing pending Type III", "error": str(e)}
                        )
                    # Clear cached pending type3 after execution attempt
                    pending["pending_type3_calls"] = []
                    pending["pending_type3_call_ids"] = []
                    pending["pending_type3_thought_signatures"] = []

                resolve_request = {
                    "pending_interaction": inference_data.get("pending_interaction"),
                    "user_reply": current_turn_message,
                    "fallback_resolution": {"resolution": "REJECT"},
                }
                resolution = self._run_resolve_client(resolve_request) or {}
                current_turn_inference_log["resolve_phase"] = {
                    "resolve_request": resolve_request,
                    "resolution": resolution,
                }

                pending = resolve_request["pending_interaction"] or {}
                pending_name = str(pending.get("name", "")).lower()
                still_missing = resolution.get("still_missing") or resolution.get(
                    "missing_fields"
                )
                resolution_flag = str(resolution.get("resolution", "")).upper()
                filled_fields = resolution.get("filled_fields")

                def _append_followup_narration(pending_payload: dict):
                    spec = INTERACTION_HANDLERS.get(pending_name)
                    if not spec:
                        return
                    print("\n ====== spec.build_narration 生成展示文本 ====== \n")
                    narration = spec.build_narration(pending_payload)
                    print("\n ====== spec.build_narration 生成展示文本 ====== \n")
                    if not narration:
                        return
                    msg = {"role": "assistant", "content": narration}
                    inference_data.setdefault("message", []).append(msg)
                    inference_data.setdefault("history", []).append(msg)
                    self._persist_history_line(history_persist_path, msg)
                    current_turn_inference_log.setdefault("resolve_followup", []).append(
                        {"role": "assistant", "content": narration, "source": "interaction_followup"}
                    )

                # Confirmation / disambiguation: CONFIRM executes, REJECT drops.
                if pending_name in {
                    "message_confirmation",
                    "message_disambiguation",
                }:
                    if resolution_flag == "CONFIRM" or resolution.get("selection"):
                        self.dialogue_state = "RUNNING"
                        self.pending_interaction = None
                        _run_pending_type3(pending)
                    elif resolution_flag == "REJECT":
                        self.dialogue_state = "RUNNING"
                        self.pending_interaction = None
                    else:
                        self.dialogue_state = "AWAITING_USER"
                        self.pending_interaction = pending
                        _append_followup_narration(self.pending_interaction.get("payload", {}))
                # Information seeking: wait until no missing fields
                elif pending_name == "message_information_seeking":
                    if filled_fields:
                        # remove filled_fields from missing_fields if both are lists/strings
                        missing_current = pending.get("payload", {}).get("missing_fields")
                        if isinstance(missing_current, list) and isinstance(filled_fields, list):
                            missing_current = [
                                m for m in missing_current if m not in filled_fields
                            ]
                            pending.setdefault("payload", {})["missing_fields"] = missing_current
                    if still_missing:
                        self.dialogue_state = "AWAITING_USER"
                        self.pending_interaction = pending
                        # carry updated missing list if provided
                        if isinstance(still_missing, (list, str)):
                            self.pending_interaction["missing_fields"] = still_missing
                            self.pending_interaction.setdefault("payload", {})[
                                "missing_fields"
                            ] = still_missing
                        _append_followup_narration(self.pending_interaction.get("payload", {}))
                    else:
                        self.dialogue_state = "RUNNING"
                        self.pending_interaction = None
                        _run_pending_type3(pending)
                else:
                    # Default: clear gate to avoid deadlock
                    self.dialogue_state = "RUNNING"
                    self.pending_interaction = None

                inference_data["dialogue_state"] = self.dialogue_state
                inference_data["pending_interaction"] = self.pending_interaction
                if self.dialogue_state == "AWAITING_USER":
                    # Stay in wait mode; skip querying model this turn.
                    current_turn_inference_log["resolve_phase"]["status"] = (
                        "still_awaiting_user"
                    )
                    all_model_response.append(current_turn_message)
                    all_inference_log.append([current_turn_inference_log])
                    total_input_token_count.append([])
                    total_output_token_count.append([])
                    total_latency.append([])
                    continue

            count = 0
            simulator_stop_pending = sim_stop
            self.dialogue_state = inference_data.get("dialogue_state", "RUNNING")
            self.pending_interaction = inference_data.get("pending_interaction")
            pending_history_entries: list[dict] = []

            def _flush_pending_history():
                for msg in pending_history_entries:
                    inference_data.setdefault("history", []).append(msg)
                    self._persist_history_line(history_persist_path, msg)
                pending_history_entries.clear()

            while True:

                print("-" * 100)
                print(
                    f"ID: {test_entry_id.replace('multi_turn_', '')}, Turn: {turn_idx}, Step: {count}"
                )
                current_step_inference_log: list[dict] = []
                # Add to the current_turn_inference_log at beginning of each step so that we don't need to bother dealing with the break statements
                current_turn_inference_log[f"step_{count}"] = current_step_inference_log

                api_response, query_latency = self._query_FC(inference_data)

                # This part of logging is disabled by default because it is too verbose and will make the result file extremely large
                # It is only useful to see if the inference pipeline is working as expected (eg, does it convert all the inputs correctly)
                if include_input_log:
                    current_step_inference_log.append(
                        {
                            "role": "inference_input",
                            "content": inference_data.get("inference_input_log", ""),
                        }
                    )
                # 读取 model 回复

                model_response_data = self._parse_query_response_FC(api_response)
                model_responses = model_response_data["model_responses"]

                # Add the assistant message to the chat history
                inference_data = self._add_assistant_message_FC(
                    inference_data, model_response_data
                )

                # Append assistant message to unified history and persist (cleaned)
                raw_assistant_history = model_response_data.get(
                    "model_responses_message_for_chat_history"
                )
                if raw_assistant_history is None:
                    raw_assistant_history = [{"role": "assistant", "content": model_responses}]
                elif isinstance(raw_assistant_history, dict):
                    raw_assistant_history = [raw_assistant_history]
                elif not isinstance(raw_assistant_history, list):
                    # Normalize non-iterables like Gemini Content objects into a single-item list
                    raw_assistant_history = [raw_assistant_history]
                pending_history_entries.extend(
                    [self.clean_assistant_for_history(m) for m in raw_assistant_history]
                )

                # Process the metadata
                # current_turn_input_token_count.append(model_response_data["input_token"])
                # current_turn_output_token_count.append(model_response_data["output_token"])
                # current_turn_latency.append(query_latency)

                current_turn_response.append(model_responses)

                reasoning_content = model_response_data.get("reasoning_content", "")
                current_turn_reasoning_content.append(reasoning_content)

                # Record assistant output for debugging/logging
                log_entry = {
                    "role": "assistant",
                    "content": model_responses,
                }
                if reasoning_content:
                    log_entry["reasoning_content"] = reasoning_content

                current_step_inference_log.append(log_entry)


                # Handle interaction tools: build narration, capture dialogue-control, remove them from execution; inject synthetic outputs to satisfy call_ids.
                original_tool_call_ids = model_response_data.get("tool_call_ids", []) or []
                (
                    narration_messages,
                    dialogue_controls,
                    model_responses,
                    filtered_tool_call_ids,
                    interaction_outputs,
                    filtered_tool_thought_signatures,
                ) = self._extract_interaction_events(
                    model_responses,
                    model_response_data.get("tool_call_ids", []),
                    model_response_data.get("tool_call_signature_map", {}),
                    model_response_data.get("tool_thought_signatures", []),
                )
                if interaction_outputs:
                    inference_data.setdefault("message", []).extend(interaction_outputs)
                    inference_data.setdefault("history", []).extend(interaction_outputs)
                    for out_msg in interaction_outputs:
                        self._persist_history_line(history_persist_path, out_msg)
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": "Injected interaction tool outputs to satisfy call_ids.",
                            "interaction_outputs": interaction_outputs,
                        }
                    )
                for narration in narration_messages:
                    msg = {"role": "assistant", "content": narration}
                    inference_data.setdefault("message", []).append(msg)
                    inference_data.setdefault("history", []).append(msg)
                    self._persist_history_line(history_persist_path, msg)
                    # 第四条消息
                    current_step_inference_log.append(
                        {
                            "role": "assistant",
                            "content": narration,
                            "source": "interaction_tool_narration",
                        }
                    )
                # Drop interaction tool call_ids before execution
                model_response_data["tool_call_ids"] = filtered_tool_call_ids
                model_response_data["tool_thought_signatures"] = (
                    filtered_tool_thought_signatures
                )
                signature_map = model_response_data.get("tool_call_signature_map")
                if signature_map is not None:
                    model_response_data["tool_call_signature_map"] = {
                        cid: signature_map.get(cid) for cid in filtered_tool_call_ids
                    }

                # If any dialogue-control tool appears, enter awaiting-user state and end this turn.
                if dialogue_controls:
                    pending = dialogue_controls[-1]
                    pending["pending_type3_calls"] = model_responses
                    pending["pending_type3_call_ids"] = filtered_tool_call_ids
                    pending["pending_type3_thought_signatures"] = (
                        filtered_tool_thought_signatures
                    )
                    self.dialogue_state = "AWAITING_USER"
                    self.pending_interaction = pending
                    inference_data["dialogue_state"] = self.dialogue_state
                    inference_data["pending_interaction"] = pending
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": "Encountered dialogue-control interaction; entering AWAITING_USER and ending turn.",
                            "pending_interaction": pending,
                        }
                    )
                    _flush_pending_history()
                    break

                decoded_model_responses = []
                decoded_has_tool_call = False
                # Try decoding the model response
                try:
                    decoded_model_responses = self.decode_execute(model_responses)
                    decoded_has_tool_call = not is_empty_execute_response(
                        decoded_model_responses
                    )
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": "Successfully decoded model response.",
                            "model_response_decoded": decoded_model_responses,
                        }
                    )

                except Exception as e:
                    print("Failed to decode the model response. Proceed to next turn.")
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": f"Error decoding the model response. Proceed to next turn.",
                            "error": str(e),
                        }
                    )
                    _flush_pending_history()
                    break

                tool_call_executed = False
                if decoded_has_tool_call:
                    if self.dialogue_state == "AWAITING_USER":
                        current_step_inference_log.append(
                            {
                                "role": "handler_log",
                                "content": "Dialogue-control pending; skipping tool execution until user resolves.",
                                "pending_interaction": self.pending_interaction,
                            }
                        )
                        break
                    # Obtain the execution results
                    execution_results, involved_instances = execute_multi_turn_func_call(
                        decoded_model_responses,
                        initial_config,
                        involved_classes,
                        self.model_name_underline_replaced,
                        test_entry_id,
                        long_context=(
                            "long_context" in test_category or "composite" in test_category
                        ),
                        is_evaL_run=False,
                    )

                    # Add the execution results to the chat history for the next turn
                    inference_data = self._add_execution_results_FC(
                        inference_data, execution_results, model_response_data
                    )

                    tool_history_entries = []
                    call_ids_exec = model_response_data.get("tool_call_ids", []) or []
                    for idx, (decoded_call, execution_result) in enumerate(
                        zip(decoded_model_responses, execution_results)
                    ):
                        call_id = call_ids_exec[idx] if idx < len(call_ids_exec) else None
                        tool_history_entries.append(
                            self._tool_result_history_entry(decoded_call, execution_result, call_id)
                        )
                    if not tool_history_entries and execution_results:
                        tool_history_entries = [
                            {"role": "tool", "name": "tool_call", "content": str(result),"tool_call_id": "BuDui!"}
                            for result in execution_results
                        ]
                    pending_history_entries.extend(tool_history_entries)

                    for execution_result, tool_call_id in zip(execution_results, call_ids_exec):
                        current_step_inference_log.append(
                            {
                                "role": "tool",
                                "content": execution_result,
                                'tool_call_id': tool_call_id
                            }
                        )
                    tool_call_executed = True
                else:
                    # If there is no tool call and nothing decoded, stop this turn.
                    if not decoded_model_responses or is_empty_execute_response(
                        decoded_model_responses
                    ):
                        break

                count += 1
                if tool_call_executed:
                    _flush_pending_history()
                    break
                # Force quit after too many steps
                if count > MAXIMUM_STEP_LIMIT:
                    force_quit = True
                    if termination_reason is None:
                        termination_reason = "max_step_limit"
                        termination_detail = f"Model forced to quit after {MAXIMUM_STEP_LIMIT} steps."
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": f"Model has been forced to quit after {MAXIMUM_STEP_LIMIT} steps.",
                        }
                    )
                    _flush_pending_history()
                    break

                _flush_pending_history()

            # End-of-turn bookkeeping: persist logs and stats once the loop exits
            all_model_response.append(current_turn_response)
            all_inference_log.append(current_turn_inference_log)
            all_reasoning_content.append(current_turn_reasoning_content)
            total_input_token_count.append(current_turn_input_token_count)
            total_output_token_count.append(current_turn_output_token_count)
            total_latency.append(current_turn_latency)

            if simulator_stop_pending:
                break

            if not exclude_state_log:
                state_log = []
                for class_name, class_instance in involved_instances.items():
                    if class_name in STATELESS_CLASSES:
                        continue
                    # Avoid modification in future turns
                    class_instance = deepcopy(class_instance)
                    state_log.append(
                        {
                            "role": "state_info",
                            "class_name": class_name,
                            "content": {
                                key: value
                                for key, value in vars(class_instance).items()
                                if not key.startswith("_")
                            },
                        }
                    )
                all_inference_log.append(state_log)

            if force_quit:
                break

        metadata = {
            "input_token_count": total_input_token_count,
            "output_token_count": total_output_token_count,
            "latency": total_latency,
            "inference_log": all_inference_log,
        }
        metadata["simulator_turns"] = simulator_turns
        if termination_reason:
            metadata["termination_reason"] = termination_reason
        if termination_detail:
            metadata["termination_detail"] = termination_detail

        if not all(
            all(content == "" for content in single_turn_reasoning_content)
            for single_turn_reasoning_content in all_reasoning_content
        ):
            metadata["reasoning_content"] = all_reasoning_content

        # Persist history at end (append already done; ensure file exists)
        if history_persist_path and not history_persist_path.exists():
            history_persist_path.touch()

        return all_model_response, metadata

    @final
    def inference_multi_turn_prompting(
        self, test_entry: dict, include_input_log: bool, exclude_state_log: bool
    ) -> tuple[list[list], dict]:
        """
        Execute a multi-turn conversation for prompting-only models where tools are
        simulated by appending execution outputs back into the conversation.
        """
        initial_config: dict = test_entry["initial_config"]
        involved_classes: list = test_entry["involved_classes"]
        test_entry_id: str = test_entry["id"]
        test_category: str = test_entry_id.rsplit("_", 1)[0]

        # This is only for the miss function category
        # A mapping from turn index to function to holdout
        holdout_function: dict[int, list] = test_entry.get("missed_function", {})

        total_input_token_count: list[list[float]] = []
        total_output_token_count: list[list[float]] = []
        total_latency: list[list[float]] = []
        # The model response that will be used for later evaluation
        all_model_response: list[list] = []
        # Only for reasoning models, reasoning content will be stored as part of metadata and in inference log
        all_reasoning_content: list[list] = []
        # The debugging log for human to understand
        all_inference_log: list[list[dict]] = []
        force_quit = False  # Whether the model has been forced to quit. If True, this whole entry will be failed.

        # Execute no function call, but just to get a reference to all the instances to get the initial state for logging purpose
        if not exclude_state_log:
            _, involved_instances = execute_multi_turn_func_call(
                [],
                initial_config,
                involved_classes,
                self.model_name_underline_replaced,
                test_entry_id,
                long_context=(
                    "long_context" in test_category or "composite" in test_category
                ),
                is_evaL_run=False,
            )
            state_log = []
            for class_name, class_instance in involved_instances.items():
                if class_name in STATELESS_CLASSES:
                    continue
                # Avoid modification in future turns
                class_instance = deepcopy(class_instance)
                state_log.append(
                    {
                        "role": "state_info",
                        "class_name": class_name,
                        "content": {
                            key: value
                            for key, value in vars(class_instance).items()
                            if not key.startswith("_")
                        },
                    }
                )
            all_inference_log.append(state_log)

        inference_data: dict = self._pre_query_processing_prompting(test_entry)

        all_multi_turn_messages: list[list[dict]] = test_entry["question"]
        for turn_idx, current_turn_message in enumerate(all_multi_turn_messages):
            current_turn_message: list[dict]

            if str(turn_idx) in holdout_function:
                assert (
                    len(current_turn_message) == 0
                ), "Holdout turn should not have user message."
                current_turn_message = [
                    {
                        "role": "user",
                        "content": DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_PROMPTING.format(
                            functions=holdout_function[str(turn_idx)]
                        ),
                    }
                ]

            if turn_idx == 0:
                inference_data = self.add_first_turn_message_prompting(
                    inference_data, current_turn_message
                )
            else:
                inference_data = self._add_next_turn_user_message_prompting(
                    inference_data, current_turn_message
                )

            current_turn_response = []
            current_turn_reasoning_content = []
            current_turn_inference_log: list[dict] = {
                "begin_of_turn_query": current_turn_message
            }
            current_turn_input_token_count: list[float] = []
            current_turn_output_token_count: list[float] = []
            current_turn_latency: list[float] = []

            count = 0
            while True:
                print("-" * 100)
                print(
                    f"ID: {test_entry_id.replace('multi_turn_', '')}, Turn: {turn_idx}, Step: {count}"
                )
                current_step_inference_log: list[dict] = []
                # Add to the current_turn_inference_log at beginning of each step so that we don't need to bother dealing with the break statements
                current_turn_inference_log[f"step_{count}"] = current_step_inference_log

                api_response, query_latency = self._query_prompting(inference_data)

                # This part of logging is disabled by default because it is too verbose and will make the result file extremely large
                # It is only useful to see if the inference pipeline is working as expected (eg, does it convert all the inputs correctly)
                if include_input_log:
                    current_step_inference_log.append(
                        {
                            "role": "inference_input",
                            "content": inference_data.get("inference_input_log", ""),
                        }
                    )

                # Try parsing the model response
                model_response_data = self._parse_query_response_prompting(api_response)
                model_responses = model_response_data["model_responses"]

                # Add the assistant message to the chat history
                inference_data = self._add_assistant_message_prompting(
                    inference_data, model_response_data
                )

                # Process the metadata
                current_turn_input_token_count.append(model_response_data["input_token"])
                current_turn_output_token_count.append(model_response_data["output_token"])
                current_turn_latency.append(query_latency)

                current_turn_response.append(model_responses)
                reasoning_content = model_response_data.get("reasoning_content", "")
                current_turn_reasoning_content.append(reasoning_content)

                log_entry = {
                    "role": "assistant",
                    "content": model_responses,
                }
                if reasoning_content:
                    log_entry["reasoning_content"] = reasoning_content

                current_step_inference_log.append(log_entry)

                # Try decoding the model response
                try:
                    decoded_model_responses = self.decode_execute(model_responses)
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": "Successfully decoded model response.",
                            "model_response_decoded": decoded_model_responses,
                        }
                    )

                    model_response_data["model_responses_decoded"] = decoded_model_responses
                    if is_empty_execute_response(decoded_model_responses):
                        print("Empty response from the model. Proceed to next turn.")
                        current_step_inference_log.append(
                            {
                                "role": "handler_log",
                                "content": f"Empty response from the model. Proceed to next turn.",
                                "model_response_decoded": decoded_model_responses,
                            }
                        )
                        break

                except Exception as e:
                    print("Failed to decode the model response. Proceed to next turn.")
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": f"Error decoding the model response. Proceed to next turn.",
                            "error": str(e),
                        }
                    )
                    break

                # Obtain the execution results
                execution_results, involved_instances = execute_multi_turn_func_call(
                    decoded_model_responses,
                    initial_config,
                    involved_classes,
                    self.model_name_underline_replaced,
                    test_entry_id,
                    long_context=(
                        "long_context" in test_category or "composite" in test_category
                    ),
                    is_evaL_run=False,
                )

                # Add the execution results to the chat history for the next turn
                inference_data = self._add_execution_results_prompting(
                    inference_data, execution_results, model_response_data
                )

                for execution_result in execution_results:
                    current_step_inference_log.append(
                        {
                            "role": "tool",
                            "content": execution_result,
                        }
                    )

                count += 1
                # Force quit after too many steps
                if count > MAXIMUM_STEP_LIMIT:
                    force_quit = True
                    current_step_inference_log.append(
                        {
                            "role": "handler_log",
                            "content": f"Model has been forced to quit after {MAXIMUM_STEP_LIMIT} steps.",
                        }
                    )
                    break

            # End-of-turn bookkeeping mirrors the FC version
            all_model_response.append(current_turn_response)
            all_reasoning_content.append(current_turn_reasoning_content)
            all_inference_log.append(current_turn_inference_log)
            total_input_token_count.append(current_turn_input_token_count)
            total_output_token_count.append(current_turn_output_token_count)
            total_latency.append(current_turn_latency)

            if not exclude_state_log:
                state_log = []
                for class_name, class_instance in involved_instances.items():
                    if class_name in STATELESS_CLASSES:
                        continue
                    # Avoid modification in future turns
                    class_instance = deepcopy(class_instance)
                    state_log.append(
                        {
                            "role": "state_info",
                            "class_name": class_name,
                            "content": {
                                key: value
                                for key, value in vars(class_instance).items()
                                if not key.startswith("_")
                            },
                        }
                    )
                all_inference_log.append(state_log)

            if force_quit:
                break

        metadata = {
            "input_token_count": total_input_token_count,
            "output_token_count": total_output_token_count,
            "latency": total_latency,
            "inference_log": all_inference_log,
        }
        # We only include reasoning content if it exists and is not empty
        if not all(
            all(content == "" for content in single_turn_reasoning_content)
            for single_turn_reasoning_content in all_reasoning_content
        ):
            metadata["reasoning_content"] = all_reasoning_content

        return all_model_response, metadata

    @final
    def inference_single_turn_FC(
        self, test_entry: dict, include_input_log: bool
    ) -> tuple[any, dict]:
        """
        Minimal single-turn FC query loop that compiles tools, sends the prompt,
        and returns the parsed response along with latency/token metadata.
        """
        inference_data: dict = {}
        inference_data = self._pre_query_processing_FC(inference_data, test_entry)
        test_entry["function"] = self._collect_functions_from_involved_classes(test_entry)
        inference_data = self._compile_tools(inference_data, test_entry)
        prompt_bundle = self.build_prompt_bundle_FC(test_entry)
        if not getattr(self, "include_interaction_history", True):
            prompt_bundle = {**prompt_bundle, "interaction_history": []}
        inference_data["system_prompts"] = prompt_bundle.get("system_prompts", [])
        inference_data["interaction_instructions"] = prompt_bundle.get(
            "interaction_instructions", []
        )
        inference_data["interaction_history"] = prompt_bundle.get("interaction_history", [])
        self._validate_prompt_requirements(
            inference_data, require_history=getattr(self, "include_interaction_history", True)
        )
        inference_data = self.add_first_turn_message_FC(
            inference_data, test_entry["question"][0]
        )
        api_response, query_latency = self._query_FC(inference_data)

        # Try parsing the model response
        model_response_data = self._parse_query_response_FC(api_response)

        # Process the metadata
        metadata: dict = {}
        if include_input_log:
            metadata["inference_log"] = [
                {
                    "role": "inference_input",
                    "content": inference_data.get("inference_input_log", ""),
                }
            ]
        metadata["input_token_count"] = model_response_data.get("input_token", 0)
        metadata["output_token_count"] = model_response_data.get("output_token", 0)
        metadata["latency"] = query_latency
        if (
            "reasoning_content" in model_response_data
            and model_response_data["reasoning_content"] != ""
        ):
            metadata["reasoning_content"] = model_response_data["reasoning_content"]

        return model_response_data["model_responses"], metadata

    @final
    def inference_single_turn_prompting(
        self, test_entry: dict, include_input_log: bool
    ) -> tuple[any, dict]:
        """
        Single-turn prompting execution for models without native tool call support.
        """
        inference_data: dict = self._pre_query_processing_prompting(test_entry)
        inference_data = self.add_first_turn_message_prompting(
            inference_data, test_entry["question"][0]
        )

        api_response, query_latency = self._query_prompting(inference_data)

        # Try parsing the model response
        model_response_data = self._parse_query_response_prompting(api_response)

        # Process the metadata
        metadata = {}
        if include_input_log:
            metadata["inference_log"] = [
                {
                    "role": "inference_input",
                    "content": inference_data.get("inference_input_log", ""),
                }
            ]
        metadata["input_token_count"] = model_response_data["input_token"]
        metadata["output_token_count"] = model_response_data["output_token"]
        metadata["latency"] = query_latency

        if (
            "reasoning_content" in model_response_data
            and model_response_data["reasoning_content"] != ""
        ):
            metadata["reasoning_content"] = model_response_data["reasoning_content"]

        return model_response_data["model_responses"], metadata

    def decode_ast(self, result, language="Python"):
        """
        This method takes raw model output (from `_parse_query_response_xxx`) and convert it to standard AST checker input.
        """
        raise NotImplementedError

    def _get_user_turn_iterator(
        self, test_entry: dict, inference_data: dict, use_user_simulator: bool
    ):
        """
        Provide an iterator over user turns.
        - Default: iterate over test_entry["question"] (prompting-style turns).
        - Simulator mode: use self.user_simulator to produce turns from high_level_instruction.
        Yields (turn_idx, current_turn_message: list[dict], simulator_trace: dict|None).
        """
        if not use_user_simulator:
            for turn_idx, current_turn_message in enumerate(test_entry["question"]):
                yield turn_idx, current_turn_message, None
            return

        simulator = getattr(self, "user_simulator", None)
        if not simulator:
            raise RuntimeError("User simulator not configured.")

        instruction = test_entry.get("high_level_instruction")
        interaction_preference = test_entry.get("interaction_preference", "")
        history = inference_data.get("message", [])
        turn_idx = 0

        while True:
            simulator_output = simulator.generate_next_turn(
                instruction, interaction_preference, history, turn_idx, test_entry
            )
            user_message = simulator_output.get("user_message") or []
            simulator_trace = simulator_output.get("trace")
            yield turn_idx, user_message, simulator_trace

            history = history + user_message
            turn_idx += 1

            # Stop if simulator asks to stop or it produced no message to avoid infinite loops
            if simulator_output.get("stop", False) or not user_message:
                break

    def decode_execute(self, result):
        """
        This method takes raw model output (from `_parse_query_response_xxx`) and convert it to standard execute checker input.
        """
        raise NotImplementedError

    def _append_termination_log(
        self,
        model_result_dir: Path,
        entries: list[dict],
        personalization_state: str,
        persona_folder: str,
    ) -> None:
        """
        Append termination events for hard stops to a JSONL log under the result folder.
        Only logs simulator repeat, history length, and max-step limits.
        """
        if not entries:
            return
        reasons_of_interest = {
            "simulator_repeat_limit",
            "history_line_limit",
            "max_step_limit",
        }
        log_entries = []
        for entry in entries:
            reason = entry.get("termination_reason")
            if not reason and entry.get("force_quit"):
                reason = "max_step_limit"
            if reason not in reasons_of_interest:
                continue
            detail = entry.get("termination_detail")
            log_entries.append(
                {
                    "id": entry.get("id"),
                    "reason": reason,
                    "detail": detail,
                    "model": self.model_name,
                    "personalization_state": personalization_state,
                    "persona": persona_folder,
                    "include_interaction_history": getattr(
                        self, "include_interaction_history", True
                    ),
                    "interaction_history_suffix": getattr(
                        self, "interaction_history_suffix", None
                    ),
                    "simulator_persona": getattr(self, "simulator_persona", None),
                }
            )
        if not log_entries:
            return
        # Cross-persona: log lives at model/personalization level.
        log_path = model_result_dir.parent / "termination_errors.log"
        with log_path.open("a", encoding="utf-8") as f:
            for log_entry in log_entries:
                f.write(json.dumps(make_json_serializable(log_entry), ensure_ascii=False) + "\n")

    @final
    def write(self, result, result_dir, update_mode=False):
        """
        Persist inference outputs under RESULT_PATH with one file per entry.

        Existing result files are left untouched; each entry writes to its own file if missing.
        """
        personalization_state = (
            "personalization" if getattr(self, "include_interaction_history", True) else "no_personalization"
        )
        model_name_dir = self.model_name.replace("/", "_")
        persona_folder = self._normalize_tag(
            getattr(self, "interaction_history_suffix", None)
            or getattr(self, "simulator_persona", None)
        )
        model_result_dir = result_dir / model_name_dir / personalization_state / persona_folder
        model_result_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(result, dict):
            result = [result]

        # Collect and format each entry for JSON compatibility
        entries_to_write = [make_json_serializable(entry) for entry in result]

        self._append_termination_log(
            model_result_dir,
            entries_to_write,
            personalization_state,
            persona_folder,
        )

        for entry in entries_to_write:
            entry_id = entry.get("id", "unknown_id")
            file_name = f"{VERSION_PREFIX}_{entry_id}_result.json"
            file_path = model_result_dir / file_name
            if file_path.exists():
                continue
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False))

    #### FC methods ####

    def _query_FC(self, inference_data: dict):
        """
        Call the model API in FC mode to get the response.
        Return the response object that can be used to feed into the `_parse_query_response_FC` method.
        """
        raise NotImplementedError

    def _pre_query_processing_FC(self, inference_data: dict, test_entry: dict) -> dict:
        """
        Preprocess the testset entry before sending it to the model.
        This might includes transforming the input user message into the format expected by the model, extract out the system prompt (if any), and any other necessary preprocessing steps. Those steps can also be done in the `add_first_turn_message_FC` and `_add_next_turn_user_message_FC` methods, but it's usually cleaner to do it here.
        The inference_data dict is updated in place and returned.

        Note: This method has different signature from its Prompting version.
        """
        raise NotImplementedError

    def _compile_tools(self, inference_data: dict, test_entry: dict) -> dict:
        """
        [Only for FC mode]
        This method is used to prepare/compile the tools from the test entry and add them to the inference data to use for model query in FC mode.
        Function docs usually need to be transformed to the format expected by the model, done through the `convert_to_tool` function from `model_handler/utils.py`.
        The inference_data dict is updated in place and returned.
        """
        raise NotImplementedError

    def _parse_query_response_FC(self, api_response: any) -> dict:
        """
        Parses the raw response from the model API to extract the result, input token count, and output token count.

        Args:
            api_response (any): The raw response from the model API.

        Returns:
            A dict containing the following elements:
                - model_responses (any): The parsed result that can be directly used as input to the decode method.
                - input_token (int): The number of tokens used in the input to the model.
                - output_token (int): The number of tokens generated by the model as output.
                - tool_call_ids (list[str]): The IDs of the tool calls that are generated by the model. Optional.
                - Any other metadata that is specific to the model.
        """
        raise NotImplementedError

    def add_first_turn_message_FC(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        """
        Add the first turn message to the chat history, in the format that the model expects.

        Args:
            inference_data (dict): The inference data from previous processing steps.
            first_turn_message (list[dict]): The first turn message from the test entry. It has variable length. It might contain one or more of the following roles:
                - "system": The system message. This role will only appear at most once, at the beginning of the first turn. For most entry, this role will not appear.
                - "user": The user message.
                - "assistant": The assistant message. For most entry, this role will not appear.

        Returns:
            inference_data (dict): The updated inference data that will be send to `_query_FC` to call the model API.
        """
        raise NotImplementedError

    def _add_next_turn_user_message_FC(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        """
        [Only for multi-turn]
        Add next turn user message to the chat history for query.
        user_message is a list of 1 element, which is guaranteed to be a `user` role message.
        """
        raise NotImplementedError

    def _add_assistant_message_FC(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        """
        Add assistant message to the chat history.
        """
        raise NotImplementedError

    def _add_execution_results_FC(
        self, inference_data: dict, execution_results: list[str], model_response_data: dict
    ) -> dict:
        """
        Add the execution results to the chat history to prepare for the next turn of query.
        Some models may need to add additional information to the chat history, such as tool call IDs.
        """
        raise NotImplementedError

    #### Prompting methods ####

    def _query_prompting(self, inference_data: dict):
        """
        Call the model API in prompting mode to get the response.
        Return the response object that can be used to feed into the decode method.
        """
        raise NotImplementedError

    def _pre_query_processing_prompting(self, test_entry: dict) -> dict:
        """
        Preprocess the testset entry before sending it to the model.
        This might includes transforming the input user message into the format expected by the model, extract out the system prompt (if any), and any other necessary preprocessing steps. Those steps can also be done in the `add_first_turn_message_prompting` and `_add_next_turn_user_message_prompting` methods, but it's usually cleaner to do it here.
        The function docs are usually supplied to the prompting models as part of the system prompt, done via the `system_prompt_pre_processing_chat_model` function from `model_handler/utils.py`, unless the model has a different way of handling it.
        Returns a dict that contains all the necessary information for the query method.
        Things like `system_prompt` and `chat_history` are optional, specific to the model.

        Note: This method has different signature from its FC version.
        """
        raise NotImplementedError

    def _parse_query_response_prompting(self, api_response: any) -> dict:
        """
        Parses the raw response from the model API to extract the result, input token count, and output token count.

        Args:
            api_response (any): The raw response from the model API.

        Returns:
            A dict containing the following elements:
                - model_responses (any): The parsed result that can be directly used as input to the decode method.
                - input_token (int): The number of tokens used in the input to the model.
                - output_token (int): The number of tokens generated by the model as output.
                - Any other metadata that is specific to the model.
        """
        raise NotImplementedError

    def add_first_turn_message_prompting(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        """
        Add the first turn message to the chat history, in the format that the model expects.
        

        Args:
            inference_data (dict): The inference data from previous processing steps.
            first_turn_message (list[dict]): The first turn message from the test entry. It has variable length. It might contain one or more of the following roles:
                - "system": The system message. This role will only appear at most once, at the beginning of the first turn.
                - "user": The user message.
                - "assistant": The assistant message. For most entry, this role will not appear.

        Returns:
            inference_data (dict): The updated inference data that will be send to `_query_prompting` to call the model API.
        """
        raise NotImplementedError

    def _add_next_turn_user_message_prompting(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        """
        [Only for multi-turn]
        Add next turn user message to the chat history for query.
        user_message is a list of 1 element, which is guaranteed to be a `user` role message.
        """
        raise NotImplementedError

    def _add_assistant_message_prompting(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        """
        Add assistant message to the chat history.
        """
        raise NotImplementedError

    def _add_execution_results_prompting(
        self, inference_data: dict, execution_results: list[str], model_response_data: dict
    ) -> dict:
        """
        将 execution 结果加到 chat history 里面, execution results to the chat history to prepare for the next turn of query.
        By default, execution results are added back as a `user` role message, as most models don't support the `tool` role in prompting mode. -- 这个不需要改
        """
        raise NotImplementedError

    def build_prompt_bundle_FC(self, test_entry: dict) -> dict:
        """
        Load system/interaction prompts and history for FC models.
        Subclasses can override to add model-specific prompt logic or sourcing.
        """
        personalization_enabled = getattr(self, "include_interaction_history", True)
        history_suffix = getattr(self, "interaction_history_suffix", None)
        return load_prompt_bundle(
            personalization_enabled=personalization_enabled,
            interaction_history_suffix=history_suffix,
        )
