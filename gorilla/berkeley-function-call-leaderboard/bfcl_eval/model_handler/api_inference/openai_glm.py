import json
import os
import time

from bfcl_eval.constants.type_mappings import GORILLA_TO_OPENAPI
from bfcl_eval.model_handler.base_handler import BaseHandler
from bfcl_eval.model_handler.model_style import ModelStyle
from bfcl_eval.model_handler.utils import (
    convert_to_function_call,
    convert_to_tool,
    default_decode_ast_prompting,
    default_decode_execute_prompting,
    format_execution_results_prompting,
    func_doc_language_specific_pre_processing,
    retry_with_backoff,
    system_prompt_pre_processing_chat_model,
)

import httpx

from bfcl_eval.user_simulator.user_simulator_openai import OpenAIUserSimulator
from openai import OpenAI, RateLimitError
from openai.types.responses import Response


class OpenAIGLMHandler(BaseHandler):
    def __init__(self, model_name, temperature) -> None:
        super().__init__(model_name, temperature)
        self.model_style = ModelStyle.OpenAI_Completions
        self.client = OpenAI(
            api_key=os.getenv("GLM_API_KEY"),
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            timeout=httpx.Timeout(timeout=300.0, connect=8.0),
        )
        self.user_simulator = OpenAIUserSimulator(model_name )

    @staticmethod
    def _substitute_prompt_role(prompts: list[dict]) -> list[dict]:
        # OpenAI allows `system` role in the prompt, but it is meant for "messages added by OpenAI"
        # For our use case, it is recommended to use `developer` role instead.
        # See https://model-spec.openai.com/2025-04-11.html#definitions
        # for prompt in prompts:
        #     if prompt["role"] == "system":
        #         prompt["role"] = "developer"

        return prompts

    def decode_ast(self, result, language="Python"):
        if "FC" in self.model_name or self.is_fc_model:
            decoded_output = []
            for invoked_function in result:
                name = list(invoked_function.keys())[0]
                params = json.loads(invoked_function[name])
                decoded_output.append({name: params})
            return decoded_output
        else:
            return default_decode_ast_prompting(result, language)

    def decode_execute(self, result):
        if "FC" in self.model_name or self.is_fc_model:
            return convert_to_function_call(result)
        else:
            return default_decode_execute_prompting(result)

    @retry_with_backoff(error_type=RateLimitError)
    def generate_with_backoff(self, **kwargs):
        start_time = time.time()
        if 'store' in kwargs:
            del kwargs['store']
        api_response = self.client.chat.completions.create(**kwargs)
        end_time = time.time()

        return api_response, end_time - start_time

    #### FC methods ####

    def _format_interaction_outputs_for_api(self, messages: list[dict]) -> list[dict]:
        """
        Convert neutral function_call_output placeholders into OpenAI tool result messages.
        """
        formatted: list[dict] = []
        system_added = False
        for message in messages:
            if isinstance(message, dict) and message.get("type") == "function_call_output":
                formatted.append(
                    {
                        "role": "user",
                        # Responses API does not accept role "tool"; send as user text.
                        "content": str(message.get("output", "")),
                    }
                )
                continue
            if isinstance(message, dict) and message.get("role"):
                role = message.get("role")
                # Prefer system over developer to match Responses API expectations
                if role == "developer":
                    role = "system"
                # Only allow a single system message at the top; drop later duplicates
                if role == "system":
                    if system_added:
                        continue
                    system_added = True
                content = message.get("content", "")
                # If content is list/dict, coerce to string to satisfy API schema.
                if isinstance(content, list) or isinstance(content, dict):
                    content = json.dumps(content, ensure_ascii=False)
                formatted.append({"role": role, "content": content})
                continue
            if isinstance(message, str):
                formatted.append({"role": "assistant", "content": message})
                continue
            # Fallback: unknown objects (e.g., Response blocks) are stringified as assistant text.
            formatted.append({"role": "assistant", "content": str(message)})
        return formatted

    def _query_FC(self, inference_data: dict):
        message: list[dict] = self._format_interaction_outputs_for_api(inference_data["message"])
        tools = inference_data["tools"]

        inference_data["inference_input_log"] = {
            "message": repr(message),
            "tools": tools,
        }

        kwargs = {
            "input": message,
            "model": self.model_name.replace("-FC", ""),
            "store": False,
            "include": [],
            "reasoning": None,
        }

        # OpenAI reasoning models don't support temperature parameter
        disallow_temperature_models = ("o3", "o4-mini", "gpt-5")
        if not any(marker in self.model_name for marker in disallow_temperature_models):
            kwargs["temperature"] = self.temperature

        if len(tools) > 0:
            kwargs["tools"] = tools


        return self.generate_with_backoff(**kwargs)

    def _query_resolve(self, messages: list[dict]) -> dict | str | None:
        """
        Resolution client for OpenAI Responses API using the same model, tools disabled.
        """
        formatted = self._format_interaction_outputs_for_api(messages)
        kwargs = {
            "input": formatted,
            "model": self.model_name.replace("-FC", ""),
            "store": False,
            "include": [],
            "reasoning": None,
        }
        disallow_temperature_models = ("o3", "o4-mini", "gpt-5")
        if not any(marker in self.model_name for marker in disallow_temperature_models):
            kwargs["temperature"] = self.temperature

        try:
            api_response, _ = self.generate_with_backoff(**kwargs)
            parsed = self._parse_query_response_FC(api_response)
            candidate = parsed.get("model_responses")
            if isinstance(candidate, list) and candidate:
                return candidate[0]
            return candidate
        except Exception:
            return None

    def _pre_query_processing_FC(self, inference_data: dict, test_entry: dict) -> dict:
        """
        Prepare request payload. In simulator mode `question` may be absent; only normalize if present.
        Initialize message container for downstream steps.
        """
        if test_entry.get("question"):
            for round_idx in range(len(test_entry["question"])):
                test_entry["question"][round_idx] = self._substitute_prompt_role(
                    test_entry["question"][round_idx]
                )

        inference_data["message"] = []

        return inference_data

    def _compile_tools(self, inference_data: dict, test_entry: dict) -> dict:
        functions: list = test_entry["function"]
        test_category: str = test_entry["id"].rsplit("_", 1)[0]

        functions = func_doc_language_specific_pre_processing(functions, test_category)
        tools = convert_to_tool(functions, GORILLA_TO_OPENAPI, self.model_style)

        inference_data["tools"] = tools

        return inference_data

    def _parse_query_response_FC(self, api_response: Response) -> dict:
        model_responses = []
        tool_call_ids = []

        # for func_call in api_response.choices[0].message:
        #     if func_call.type == "function_call":
        #         model_responses.append({func_call.name: func_call.arguments})
        #         tool_call_ids.append(func_call.call_id)

        # if not model_responses:  # If there are no function calls
        #     model_responses = api_response.output_text

        message = api_response.choices[0].message

        if message.tool_calls:

            for func_call in message.tool_calls:
                tool_call_ids.append(func_call.id)
                model_responses.append({func_call.function.name: func_call.function.arguments})

            


        # OpenAI reasoning models don't show full reasoning content in the api response,
        # but only a summary of the reasoning content.
        # reasoning_content = ""
        # for item in api_response.output:
        #     if item.type == "reasoning":
        #         for summary in item.summary:
        #             reasoning_content += summary.text + "\n"

        return {
            "model_responses": model_responses,
            "model_responses_message_for_chat_history": message.content,
            "tool_call_ids": tool_call_ids,
            # "reasoning_content": reasoning_content,
            # "input_token": api_response.usage.input_tokens,
            # "output_token": api_response.usage.output_tokens,
        }

    def add_first_turn_message_FC(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        prepended = self._collect_prepended_prompts(inference_data)
        if prepended:
            first_turn_message = prepended + first_turn_message
        first_turn_message = self._substitute_prompt_role(first_turn_message)
        inference_data.setdefault("message", [])
        inference_data["message"].extend(first_turn_message)
        inference_data["chat_history"] = inference_data.get("message", [])
        return inference_data

    def _add_next_turn_user_message_FC(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        user_message = self._substitute_prompt_role(user_message)
        inference_data["message"].extend(user_message)
        inference_data["chat_history"] = inference_data.get("message", [])
        return inference_data

    def _add_assistant_message_FC(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        inference_data["message"].extend(
            model_response_data["model_responses_message_for_chat_history"]
        )
        return inference_data

    def _add_execution_results_FC(
        self,
        inference_data: dict,
        execution_results: list[str],
        model_response_data: dict,
    ) -> dict:
        # Add the execution results to the current round result, one at a time
        for execution_result, tool_call_id in zip(
            execution_results, model_response_data["tool_call_ids"]
        ):
            tool_message = {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": execution_result,
            }
            inference_data["message"].append(tool_message)

        return inference_data

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

    #### Prompting methods ####

    def _query_prompting(self, inference_data: dict):
        inference_data["inference_input_log"] = {"message": repr(inference_data["message"])}

        kwargs = {
            "input": inference_data["message"],
            "model": self.model_name.replace("-FC", ""),
            "store": False,
            "include": [],
            "reasoning": None,
        }

        # OpenAI reasoning models don't support temperature parameter
        disallow_temperature_models = ("o3", "o4-mini", "gpt-5")
        if not any(marker in self.model_name for marker in disallow_temperature_models):
            kwargs["temperature"] = self.temperature

        return self.generate_with_backoff(**kwargs)

    def _pre_query_processing_prompting(self, test_entry: dict) -> dict:
        functions: list = test_entry["function"]
        test_category: str = test_entry["id"].rsplit("_", 1)[0]

        functions = func_doc_language_specific_pre_processing(functions, test_category)

        test_entry["question"][0] = system_prompt_pre_processing_chat_model(
            test_entry["question"][0], functions, test_category
        )

        for round_idx in range(len(test_entry["question"])):
            test_entry["question"][round_idx] = self._substitute_prompt_role(
                test_entry["question"][round_idx]
            )

        return {"message": []}

    def _parse_query_response_prompting(self, api_response: Response) -> dict:
        # OpenAI reasoning models don't show full reasoning content in the api response,
        # but only a summary of the reasoning content.
        reasoning_content = ""
        for item in api_response.output:
            if item.type == "reasoning":
                for summary in item.summary:
                    reasoning_content += summary.text + "\n"

        return {
            "model_responses": api_response.output_text,
            "model_responses_message_for_chat_history": api_response.output,
            "reasoning_content": reasoning_content,
            # "input_token": api_response.usage.input_tokens,
            # "output_token": api_response.usage.output_tokens,
        }

    def add_first_turn_message_prompting(
        self, inference_data: dict, first_turn_message: list[dict]
    ) -> dict:
        inference_data["message"].extend(first_turn_message)
        return inference_data

    def _add_next_turn_user_message_prompting(
        self, inference_data: dict, user_message: list[dict]
    ) -> dict:
        inference_data["message"].extend(user_message)
        return inference_data

    def _add_assistant_message_prompting(
        self, inference_data: dict, model_response_data: dict
    ) -> dict:
        inference_data["message"].extend(
            model_response_data["model_responses_message_for_chat_history"]
        )
        return inference_data

    def _add_execution_results_prompting(
        self,
        inference_data: dict,
        execution_results: list[str],
        model_response_data: dict,
    ) -> dict:
        formatted_results_message = format_execution_results_prompting(
            inference_data, execution_results, model_response_data
        )
        inference_data["message"].append(
            {"role": "user", "content": formatted_results_message}
        )

        return inference_data
