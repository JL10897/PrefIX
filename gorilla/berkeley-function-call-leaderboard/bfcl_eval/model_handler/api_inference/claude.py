import json
import os
import time

from anthropic import Anthropic, RateLimitError
from anthropic.types import TextBlock, ToolUseBlock
from bfcl_eval.model_handler.base_handler import BaseHandler
from bfcl_eval.constants.type_mappings import GORILLA_TO_OPENAPI
from bfcl_eval.model_handler.model_style import ModelStyle
from bfcl_eval.model_handler.utils import (
    ast_parse,
    combine_consecutive_user_prompts,
    convert_system_prompt_into_user_prompt,
    convert_to_function_call,
    convert_to_tool,
    extract_system_prompt,
    format_execution_results_prompting,
    func_doc_language_specific_pre_processing,
    retry_with_backoff,
    system_prompt_pre_processing_chat_model,
)
from bfcl_eval.user_simulator.user_simulator_openai import OpenAIUserSimulator
from bfcl_eval.utils import is_multi_turn


class ClaudeHandler(BaseHandler):
    def __init__(self, model_name, temperature) -> None:
        super().__init__(model_name, temperature)
        self.model_style = ModelStyle.Anthropic
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        # Anthropic tool-use models may not include "FC" in the name; force FC path when matched.
        fc_models = (
            "claude-3-5-sonnet-20241022",
            "claude-sonnet-4-5-20250929",
        )
        if any(m in model_name for m in fc_models):
            self.is_fc_model = True
        self.user_simulator = OpenAIUserSimulator(model_name)

    def decode_ast(self, result, language="Python"):
        if "FC" not in self.model_name:
            func = result
            if " " == func[0]:
                func = func[1:]
            if not func.startswith("["):
                func = "[" + func
            if not func.endswith("]"):
                func = func + "]"
            decode_output = ast_parse(func, language)
            return decode_output

        else:
            decoded_output = []
            for invoked_function in result:
                name = list(invoked_function.keys())[0]
                params = json.loads(invoked_function[name])
                decoded_output.append({name: params})
            return decoded_output

    def decode_execute(self, result):
        if "FC" not in self.model_name:
            func = result
            if " " == func[0]:
                func = func[1:]
            if not func.startswith("["):
                func = "[" + func
            if not func.endswith("]"):
                func = func + "]"
            decode_output = ast_parse(func)
            execution_list = []
            for function_call in decode_output:
                for key, value in function_call.items():
                    execution_list.append(
                        f"{key}({','.join([f'{k}={repr(v)}' for k, v in value.items()])})"
                    )
            return execution_list

        else:
            function_call = convert_to_function_call(result)
            return function_call

    @retry_with_backoff(error_type=RateLimitError)
    def generate_with_backoff(self, **kwargs):
        start_time = time.time()
        api_response = self.client.messages.create(**kwargs)
        end_time = time.time()

        return api_response, end_time - start_time

    def _get_max_tokens(self):
        """
        max_tokens is required to be set when querying, so we default to the model's max tokens
        """
        if "claude-opus-4-20250514" in self.model_name:
            return 32000
        elif "claude-opus-4-5-20251101" in self.model_name:
            # TODO: update if Anthropic publishes a different context window for Opus 4.5
            return 64000
        elif "claude-sonnet-4-5-20250929" in self.model_name:
            return 64000
        elif "claude-sonnet-4-20250514" in self.model_name:
            return 64000
        elif "claude-3-5-haiku-20241022" in self.model_name:
            return 8192
        else:
            raise ValueError(f"Unsupported model: {self.model_name}")

    def _get_user_turn_iterator(
        self, test_entry: dict, inference_data: dict, use_user_simulator: bool
    ):
        """
        Use the configured user simulator when high_level_instruction is provided; otherwise fall back to base iteration.
        """
        if not use_user_simulator:
            yield from super()._get_user_turn_iterator(test_entry, inference_data, False)
            return

        simulator = getattr(self, "user_simulator", None)
        if not simulator:
            raise RuntimeError("User simulator not configured.")

        instruction = test_entry.get("high_level_instruction")
        interaction_preference = test_entry.get("interaction_preference", "")
        history = inference_data.get("message", [])
        turn_idx = 0

        def _normalize_user_messages(raw_messages: any) -> list[dict]:
            """
            Coerce simulator outputs into Anthropic Messages format with explicit role and typed content list.
            """
            if raw_messages is None:
                return []
            if isinstance(raw_messages, dict):
                raw_messages = [raw_messages]
            normalized: list[dict] = []
            for msg in raw_messages:
                if not isinstance(msg, dict):
                    normalized.append(
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": str(msg)}],
                        }
                    )
                    continue
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if isinstance(content, list):
                    normalized.append({"role": role, "content": content})
                else:
                    normalized.append(
                        {
                            "role": role,
                            "content": [{"type": "text", "text": str(content)}],
                        }
                    )
            return normalized

        while True:
            simulator_output = simulator.generate_next_turn(
                instruction, interaction_preference, history, turn_idx, test_entry
            )
            user_message = _normalize_user_messages(simulator_output.get("user_message"))
            simulator_trace = simulator_output.get("trace")
            yield turn_idx, user_message, simulator_trace

            history = history + user_message
            turn_idx += 1

            # Stop if simulator asks to stop or it produced no message to avoid infinite loops
            if simulator_output.get("stop", False) or not user_message:
                break

    #### FC methods ####

    def _format_interaction_outputs_for_api(self, messages: list[dict]) -> list[dict]:
        """
        Normalize messages for Anthropic and enforce tool_use -> tool_result adjacency.
        Handles dict messages, TextBlock, and ToolUseBlock objects. For each assistant
        message containing tool_use, immediately insert a user tool_result message for
        those ids (content may be empty if result not yet present).
        """
        tool_results_map: dict[str, str] = {}
        formatted: list[dict] = []

        def normalize_msg(msg: any) -> dict | None:
            if isinstance(msg, dict) and msg.get("type") == "function_call_output":
                tool_results_map[msg.get("call_id") or ""] = msg.get("output", "")
                return None
            if isinstance(msg, dict) and msg.get("role") == "tool":
                tool_results_map[msg.get("call_id") or msg.get("tool_use_id") or ""] = msg.get(
                    "content", ""
                )
                return None
            # Collect standalone tool_result messages and drop them (we will re-insert adjacent to tool_use)
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list):
                    has_tool_result = False
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            has_tool_result = True
                            tool_results_map[block.get("tool_use_id") or ""] = block.get(
                                "content", ""
                            )
                    if has_tool_result:
                        return None
            if isinstance(msg, ToolUseBlock):
                return {"role": "assistant", "content": [msg]}
            if isinstance(msg, TextBlock):
                return {"role": "assistant", "content": [{"type": "text", "text": msg.text}]}
            if isinstance(msg, dict) and msg.get("role"):
                return msg
            if isinstance(msg, str):
                return {"role": "assistant", "content": [{"type": "text", "text": msg}]}
            return None

        for raw in messages:
            msg = normalize_msg(raw)
            if not msg:
                continue
            formatted.append(msg)
            if msg.get("role") != "assistant":
                continue
            content_list = msg.get("content", [])
            if not isinstance(content_list, list):
                continue
            tool_use_ids: list[str] = []
            for block in content_list:
                if isinstance(block, ToolUseBlock):
                    tool_use_ids.append(block.id)
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_use_ids.append(block.get("id", ""))
            if not tool_use_ids:
                continue
            # Immediately follow with tool_result for these ids (content may be empty)
            formatted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "content": tool_results_map.get(tu_id, ""),
                            "tool_use_id": tu_id,
                        }
                        for tu_id in tool_use_ids
                    ],
                }
            )

        return formatted

    def _query_FC(self, inference_data: dict):
        inference_data["inference_input_log"] = {
            "message": repr(inference_data["message"]),
            "tools": inference_data["tools"],
        }
        # Sanitize messages: keep only role-bearing entries; convert function_call_output stubs to tool_result blocks.
        messages = self._format_interaction_outputs_for_api(inference_data["message"])

        if inference_data["caching_enabled"]:
            # Only add cache control to the last two user messages
            # Remove previously set cache control flags from all user messages except the last two
            count = 0
            for message in reversed(messages):
                if message["role"] == "user":
                    if count < 2:
                        message["content"][0]["cache_control"] = {"type": "ephemeral"}
                    else:
                        if "cache_control" in message["content"][0]:
                            del message["content"][0]["cache_control"]
                    count += 1

    
        # Need to set timeout to avoid auto-error when requesting large context length
        # https://github.com/anthropics/anthropic-sdk-python#long-requests
        return self.generate_with_backoff(
            model=self.model_name.strip("-FC"),
            max_tokens=self._get_max_tokens(),
            tools=inference_data["tools"],
            temperature=self.temperature,
            messages=messages,
            timeout=1200,
        )

    def _query_resolve(self, messages: list[dict]) -> dict | str | None:
        """
        Resolution client using Anthropic Messages with tools disabled.
        """
        formatted: list[dict] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content", "")
            if not role:
                continue
            formatted.append(
                {
                    "role": role,
                    "content": [{"type": "text", "text": str(content)}],
                }
            )

        try:
            api_response, _ = self.generate_with_backoff(
                model=self.model_name.strip("-FC"),
                max_tokens=self._get_max_tokens(),
                tools=[],
                temperature=self.temperature,
                messages=formatted,
            )
            text_parts = []
            for block in api_response.content:
                if hasattr(block, "text"):
                    text_parts.append(str(block.text))
            joined = "\n".join([t for t in text_parts if t])
            if not joined:
                return None
            try:
                return json.loads(joined)
            except Exception:
                return joined
        except Exception:
            return None

    def _pre_query_processing_FC(self, inference_data: dict, test_entry: dict) -> dict:
        if test_entry.get("question"):
            for round_idx in range(len(test_entry["question"])):
                test_entry["question"][round_idx] = convert_system_prompt_into_user_prompt(
                    test_entry["question"][round_idx]
                )
                test_entry["question"][round_idx] = combine_consecutive_user_prompts(
                    test_entry["question"][round_idx]
                )
        inference_data["message"] = []

        test_entry_id: str = test_entry["id"]
        test_category: str = test_entry_id.rsplit("_", 1)[0]
        # caching enabled only for multi_turn category
        inference_data["caching_enabled"] = is_multi_turn(test_category)

        return inference_data

    def _compile_tools(self, inference_data: dict, test_entry: dict) -> dict:
        functions: list = test_entry["function"]
        test_category: str = test_entry["id"].rsplit("_", 1)[0]

        functions = func_doc_language_specific_pre_processing(functions, test_category)
        tools = convert_to_tool(functions, GORILLA_TO_OPENAPI, self.model_style)

        if inference_data["caching_enabled"]:
            # First time compiling tools, so adding cache control flag to the last tool
            if "tools" not in inference_data:
                tools[-1]["cache_control"] = {"type": "ephemeral"}
            # This is the situation where the tools are already compiled and we are adding more tools to the existing tools (in miss_func category)
            # We add the cache control flag to the last tool in the previous existing tools and the last tool in the new tools to maximize cache hit
            else:
                existing_tool_len = len(inference_data["tools"])
                tools[existing_tool_len - 1]["cache_control"] = {"type": "ephemeral"}
                tools[-1]["cache_control"] = {"type": "ephemeral"}

        inference_data["tools"] = tools

        return inference_data

    def _parse_query_response_FC(self, api_response: any) -> dict:
        text_outputs = []
        tool_call_outputs = []
        tool_call_ids = []

        for content in api_response.content:
            if isinstance(content, TextBlock):
                text_outputs.append(content.text)
            elif isinstance(content, ToolUseBlock):
                tool_call_outputs.append({content.name: json.dumps(content.input)})
                tool_call_ids.append(content.id)

        model_responses = tool_call_outputs if tool_call_outputs else text_outputs

        model_responses_message_for_chat_history = api_response.content

        return {
            "model_responses": model_responses,
            "model_responses_message_for_chat_history": model_responses_message_for_chat_history,
            "tool_call_ids": tool_call_ids,
            "input_token": api_response.usage.input_tokens,
            "output_token": api_response.usage.output_tokens,
        }

    def add_first_turn_message_FC(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        inference_data.setdefault("message", [])
        # Anthropic Messages API does not allow "system" role inside messages; treat prepended prompts as user text.
        prepended = self._collect_prepended_prompts(inference_data, default_role="user")
        for message in prepended:
            message["content"] = [{"type": "text", "text": message.get("content", "")}]
        if prepended:
            inference_data["message"].extend(prepended)
        for message in first_turn_message:
            message["content"] = [{"type": "text", "text": message["content"]}]
        inference_data["message"].extend(first_turn_message)
        inference_data["chat_history"] = inference_data.get("message", [])
        return inference_data

    def _add_next_turn_user_message_FC(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        for message in user_message:
            message["content"] = [{"type": "text", "text": message["content"]}]
        inference_data["message"].extend(user_message)
        inference_data["chat_history"] = inference_data.get("message", [])
        return inference_data

    def _add_assistant_message_FC(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        inference_data["message"].append(
            {
                "role": "assistant",
                "content": model_response_data["model_responses_message_for_chat_history"],
            }
        )
        return inference_data

    def _add_execution_results_FC(
        self,
        inference_data: dict,
        execution_results: list[str],
        model_response_data: dict,
    ) -> dict:
        # Claude don't use the tool role; it uses the user role to send the tool output
        tool_message = {
            "role": "user",
            "content": [],
        }
        for execution_result, tool_call_id in zip(
            execution_results, model_response_data["tool_call_ids"]
        ):
            tool_message["content"].append(
                {
                    "type": "tool_result",
                    "content": execution_result,
                    "tool_use_id": tool_call_id,
                }
            )

        inference_data["message"].append(tool_message)

        return inference_data

    #### Prompting methods ####

    def _query_prompting(self, inference_data: dict):
        inference_data["inference_input_log"] = {
            "message": repr(inference_data["message"]),
            "system_prompt": inference_data["system_prompt"],
        }

        if inference_data["caching_enabled"]:
            # Cache the system prompt
            inference_data["system_prompt"][0]["cache_control"] = {"type": "ephemeral"}
            # Add cache control to the last two user messages as well
            count = 0
            for message in reversed(inference_data["message"]):
                if message["role"] == "user":
                    if count < 2:
                        message["content"][0]["cache_control"] = {"type": "ephemeral"}
                    else:
                        if "cache_control" in message["content"][0]:
                            del message["content"][0]["cache_control"]
                    count += 1

        # Need to set timeout to avoid auto-error when requesting large context length
        # https://github.com/anthropics/anthropic-sdk-python#long-requests
        return self.generate_with_backoff(
            model=self.model_name,
            max_tokens=self._get_max_tokens(),
            temperature=self.temperature,
            system=inference_data["system_prompt"],
            messages=inference_data["message"],
            timeout=1200,
        )

    def _pre_query_processing_prompting(self, test_entry: dict) -> dict:
        functions: list = test_entry["function"]
        test_entry_id: str = test_entry["id"]
        test_category: str = test_entry_id.rsplit("_", 1)[0]

        functions = func_doc_language_specific_pre_processing(functions, test_category)

        test_entry["question"][0] = system_prompt_pre_processing_chat_model(
            test_entry["question"][0], functions, test_category
        )
        # Claude takes in system prompt in a specific field, not in the message field, so we don't need to add it to the message
        system_prompt = extract_system_prompt(test_entry["question"][0])

        system_prompt = [{"type": "text", "text": system_prompt}]

        # Claude doesn't allow consecutive user prompts, so we need to combine them
        for round_idx in range(len(test_entry["question"])):
            test_entry["question"][round_idx] = combine_consecutive_user_prompts(
                test_entry["question"][round_idx]
            )

        test_entry_id: str = test_entry["id"]
        test_category: str = test_entry_id.rsplit("_", 1)[0]
        # caching enabled only for multi_turn category
        caching_enabled: bool = is_multi_turn(test_category)

        return {
            "message": [],
            "system_prompt": system_prompt,
            "caching_enabled": caching_enabled,
        }

    def _parse_query_response_prompting(self, api_response: any) -> dict:
        return {
            "model_responses": api_response.content[0].text,
            "input_token": api_response.usage.input_tokens,
            "output_token": api_response.usage.output_tokens,
        }

    def add_first_turn_message_prompting(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        for message in first_turn_message:
            message["content"] = [{"type": "text", "text": message["content"]}]
        inference_data["message"].extend(first_turn_message)
        return inference_data

    def _add_next_turn_user_message_prompting(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        for message in user_message:
            message["content"] = [{"type": "text", "text": message["content"]}]
        inference_data["message"].extend(user_message)
        return inference_data

    def _add_assistant_message_prompting(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        inference_data["message"].append(
            {
                "role": "assistant",
                "content": model_response_data["model_responses"],
            }
        )
        return inference_data

    def _add_execution_results_prompting(
        self, inference_data: dict, execution_results: list[str], model_response_data: dict
    ) -> dict:
        formatted_results_message = format_execution_results_prompting(
            inference_data, execution_results, model_response_data
        )
        inference_data["message"].append(
            {
                "role": "user",
                "content": [{"type": "text", "text": formatted_results_message}],
            }
        )

        return inference_data
