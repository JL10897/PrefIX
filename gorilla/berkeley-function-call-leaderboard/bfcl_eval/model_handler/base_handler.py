import json
import time
from copy import deepcopy

from bfcl_eval.constants.category_mapping import (
    MULTI_TURN_FUNC_DOC_FILE_MAPPING,
    VERSION_PREFIX,
)
from bfcl_eval.constants.default_prompts import (
    DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC,
    DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_PROMPTING,
    MAXIMUM_STEP_LIMIT,
)
from bfcl_eval.constants.eval_config import MULTI_TURN_FUNC_DOC_PATH, RESULT_PATH
from bfcl_eval.eval_checker.multi_turn_eval.multi_turn_utils import (
    STATELESS_CLASSES,
    execute_multi_turn_func_call,
    is_empty_execute_response,
)
from pathlib import Path

from bfcl_eval.model_handler.model_style import ModelStyle
from bfcl_eval.utils import load_file, make_json_serializable, sort_key
from bfcl_eval.user_simulator.user_simulator_openai import OpenAIUserSimulator
from typing import Any, Optional

try:
    from bfcl_eval.scheduler.scheduler_base import (
        ActionItem,
        PlanResult,
        SchedulerBase,
        SupervisionResult,
        serialize_action_items,
    )
    from bfcl_eval.scheduler.scheduler_openai import OpenAIScheduler
except Exception:
    SchedulerBase = None  # type: ignore
    PlanResult = None  # type: ignore
    SupervisionResult = None  # type: ignore
    ActionItem = None  # type: ignore
    serialize_action_items = None  # type: ignore
    OpenAIScheduler = None  # type: ignore
from overrides import final


class BaseHandler:
    model_name: str
    model_style: ModelStyle

    def __init__(
        self,
        model_name,
        temperature,
        scheduler: Optional["SchedulerBase"] = None,
        step_budget: int = 5,
    ) -> None:
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
        # Optional scheduler (planner “brain”) injected via factory/config.
        self.scheduler: Optional["SchedulerBase"] = scheduler
        self.scheduler_step_budget = step_budget

    def _append_scheduler_message(
        self,
        inference_data: dict,
        content: str,
        role: str = "user",
        test_entry_id: str | None = None,
        turn: int | None = None,
        step: int | None = None,
    ) -> None:
        """
        Inject scheduler guidance into the model-facing message list for the
        current round without polluting user/simulator history persistence.
        """
        if not content:
            return
        message = {"role": role, "content": content}
        inference_data.setdefault("message", [])
        inference_data["message"].append(message)
        if test_entry_id:
            self._persist_scheduler_log(
                test_entry_id,
                {
                    "type": "scheduler_message",
                    "role": role,
                    "content": content,
                    "turn": turn,
                    "step": step,
                },
            )

    @staticmethod
    def _format_plan_instruction(plan_result: Optional["PlanResult"]) -> str:
        """
        Turn a scheduler plan into a compact instruction string for the model.
        """
        if not plan_result:
            return ""
        lines = ["[Scheduler] Follow the strategy step by step."]
        intention = getattr(plan_result.strategy_plan, "intention", None)
        if intention:
            lines.append(f"Intention: {intention}")
        actions = getattr(plan_result, "actions", []) or []
        if actions:
            rendered = []
            for idx, action in enumerate(actions, 1):
                tool = getattr(action, "tool", "") or "unknown_tool"
                args = getattr(action, "args", {}) or {}
                rendered.append(f"{idx}. {tool} {json.dumps(args, ensure_ascii=False)}")
            lines.append("Planned actions:")
            lines.extend(rendered)
            lines.append("Execute the next action only, then wait.")
        return "\n".join(lines)

    @staticmethod
    def _format_remaining_actions(actions: Any) -> str:
        if not actions:
            return ""
        rendered = []
        for idx, action in enumerate(actions, 1):
            tool = getattr(action, "tool", "") or "unknown_tool"
            args = getattr(action, "args", {}) or {}
            rendered.append(f"{idx}. {tool} {json.dumps(args, ensure_ascii=False)}")
        return "[Scheduler] Continue with remaining actions:\n" + "\n".join(rendered)

    @staticmethod
    def _format_action_prompt(action_idx: int, action: Any) -> str:
        tool = getattr(action, "tool", "") or "unknown_tool"
        args = getattr(action, "args", {}) or {}
        return (
            "[Scheduler] Execute the next planned action.\n"
            f"Action {action_idx + 1}: tool={tool}, args={json.dumps(args, ensure_ascii=False)}\n"
            "Call exactly this tool with the provided args. Do not execute other tools."
        )

    @staticmethod
    def _action_to_dict(action: Any) -> dict:
        """
        Convert an action-like object (e.g., ActionItem) into a JSON-serializable dict.
        """
        if not action:
            return {}
        if "serialize_action_items" in globals() and serialize_action_items:
            serialized = serialize_action_items([action])
            return serialized[0] if serialized else {}
        return {
            "tool": getattr(action, "tool", ""),
            "args": getattr(action, "args", None),
            "raw": getattr(action, "raw", None),
        }

    @staticmethod
    def _ensure_json_serializable(payload: Any, context: str = "") -> Any:
        """
        Best-effort guard to keep scheduler payloads JSON-serializable.
        """
        try:
            json.dumps(payload)
            return payload
        except TypeError:
            safe_payload = make_json_serializable(payload)
            # If this still fails, let it propagate for visibility.
            json.dumps(safe_payload)
            return safe_payload

    @staticmethod
    def _persist_history_line(history_persist_path: Path | None, msg: dict) -> None:
        if not history_persist_path:
            return
        with history_persist_path.open("a", encoding="utf8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

    def _scheduler_log_path(self, test_entry_id: str) -> Path:
        scheduler_dir = RESULT_PATH / "scheduler_logs" / self.model_name_underline_replaced
        scheduler_dir.mkdir(parents=True, exist_ok=True)
        return scheduler_dir / f"{test_entry_id}.jsonl"

    def _persist_scheduler_log(self, test_entry_id: str, payload: dict) -> None:
        """
        Append scheduler interaction logs (per turn) to a dedicated file.
        """
        try:
            log_path = self._scheduler_log_path(test_entry_id)
            with log_path.open("a", encoding="utf8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            # Logging best-effort; do not break handler flow.
            pass

    def _run_scheduler_plan(
        self, message: list[dict], inference_history: list[dict], test_entry_id: str
    ) -> Optional["PlanResult"]:
        """
        If a scheduler is configured, run its plan and persist the raw plan for debugging.
        """
        if not self.scheduler:
            return None
        plan_result = None
        try:
            plan_result = self.scheduler.plan(message=message, history=inference_history)
            plan_payload = {
                "strategy_plan": getattr(plan_result, "strategy_plan", None).__dict__
                if plan_result and getattr(plan_result, "strategy_plan", None)
                else None,
                "actions": [
                    self._action_to_dict(action)
                    for action in getattr(plan_result, "actions", []) or []
                ]
                if plan_result
                else [],
                "validated_tools": getattr(plan_result, "validated_tools", None)
                if plan_result
                else None,
                "note": getattr(plan_result, "note", None) if plan_result else None,
            }
            self._persist_scheduler_log(
                test_entry_id,
                {
                    "type": "scheduler_plan",
                    "message": message,
                    "history": inference_history,
                    "plan": make_json_serializable(plan_payload),
                },
            )
        except Exception as e:
            self._persist_scheduler_log(
                test_entry_id,
                {
                    "type": "scheduler_plan_error",
                    "error": str(e),
                },
            )
        return plan_result

    def _ensure_scheduler(self, tools: list[Any], test_entry: dict) -> None:
        """
        Lazily create a default OpenAI scheduler if none was provided.
        """
        if self.scheduler or not SchedulerBase or not OpenAIScheduler:
            return
        user_profile = test_entry.get("user_profile") or {}
        try:
            self.scheduler = OpenAIScheduler(
                model_api=self.model_name,
                tools=tools,
                user_profile=user_profile,
                step_budget=self.scheduler_step_budget,
            )
        except Exception as e:
            # Best-effort; if scheduler fails to init, continue without it.
            self._persist_scheduler_log(
                test_entry.get("id", "unknown_id"),
                {
                    "type": "scheduler_init_error",
                    "error": str(e),
                },
            )

    def _run_scheduler_supervision(
        self,
        plan_result: Optional["PlanResult"],
        fc_outputs: Any,
        test_entry_id: str,
        state: Optional[dict] = None,
        history: Optional[list] = None,
    ) -> Optional["SupervisionResult"]:
        if not self.scheduler or plan_result is None:
            return None
        # Prepare a log-friendly snapshot to avoid serializing dataclass objects.
        def _serialize_state(raw_state: dict | None) -> dict:
            if not raw_state:
                return {}
            plan_actions = []
            plan_obj = raw_state.get("plan")
            if plan_obj is not None:
                try:
                    plan_actions = [
                        self._action_to_dict(action)
                        for action in getattr(plan_obj, "actions", []) or []
                    ]
                except Exception:
                    plan_actions = []
            return {
                "cursor": raw_state.get("cursor", 0),
                "executed": [
                    self._action_to_dict(action)
                    for action in raw_state.get("executed", []) or []
                ],
                "plan_actions": plan_actions,
            }

        def _serialize_supervision(supervision_obj: Any) -> dict:
            if not supervision_obj:
                return {}
            return {
                "status": getattr(supervision_obj, "status", None),
                "remaining_actions": [
                    self._action_to_dict(a)
                    for a in getattr(supervision_obj, "remaining_actions", []) or []
                ],
                "final_actions": [
                    self._action_to_dict(a)
                    for a in getattr(supervision_obj, "final_actions", []) or []
                ],
                "validated_tools": getattr(supervision_obj, "validated_tools", None),
                "assistant_message": getattr(supervision_obj, "assistant_message", None),
                "guidance": getattr(supervision_obj, "guidance", None),
            }

        try:
            sanitized_state = self._ensure_json_serializable(
                _serialize_state(state or {}), context="scheduler_state"
            )
            supervision = self.scheduler.supervise(
                plan_result=plan_result,
                fc_outputs=fc_outputs,
                state=sanitized_state,
                history=history or [],
            )
            self._persist_scheduler_log(
                test_entry_id,
                {
                    "type": "scheduler_supervision",
                    "fc_outputs": fc_outputs,
                    "state": sanitized_state,
                    "supervision": _serialize_supervision(supervision),
                },
            )
            return supervision
        except Exception as e:
            self._persist_scheduler_log(
                test_entry_id,
                {
                    "type": "scheduler_supervision_error",
                    "error": str(e),
                },
            )
            return None

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
        if isinstance(raw_message, dict):
            role = raw_message.get("role", "assistant")
            content = raw_message.get("content", "")
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
            return {"role": role, "content": content}

        return {"role": "assistant", "content": str(raw_message)}

    @staticmethod
    def _tool_result_history_entry(tool_call: any, execution_result: any) -> dict:
        tool_name = ""
        if isinstance(tool_call, str):
            tool_name = tool_call.split("(", 1)[0]
            if "." in tool_name:
                tool_name = tool_name.split(".")[-1]
        tool_name = tool_name or "tool_call"
        return {"role": "tool", "name": tool_name, "content": str(execution_result)}

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

        # use_user_simulator: bool = bool(
        #     getattr(self, "user_simulator", None)
        #     and test_entry.get("high_level_instruction")
        # )

        # if not use_user_simulator:
        #     raise RuntimeError(
        #         f"Simulator or high_level_instruction missing for entry {test_entry_id}; question-based flow disabled."
        #     )

        use_user_simulator = True

        # 如果是 OpenAIUserSimulator，确保 persona 设置
        if isinstance(self.user_simulator, OpenAIUserSimulator):
            self.user_simulator.persona_name = getattr(self, "simulator_persona", None)

        # 历史存储初始化（持久化）
        history_root = Path(
            "/Users/JL/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/gorilla/berkeley-function-call-leaderboard/bfcl_eval/user_simulator/history"
        )
        history_dir = history_root / self.model_name_underline_replaced
        history_dir.mkdir(parents=True, exist_ok=True)
        history_persist_path = history_dir / f"{test_entry_id}.json"

        inference_data["history"] = []
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

        # 在这里直接循环，使用模拟器生成 user turn
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
                if content == "<END_SIMULATION>":
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

            if str(turn_idx) in holdout_function:
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

            if turn_idx == 0:
                inference_data = self.add_first_turn_message_FC(
                    inference_data, current_turn_message
                )
            else:
                inference_data = self._add_next_turn_user_message_FC(
                    inference_data, current_turn_message
                )
            # Optional scheduler planning for this turn.
            if turn_idx == 0:
                # Ensure scheduler exists after tools compiled for the entry.
                self._ensure_scheduler(test_entry.get("function", []), test_entry)
            # Maintain scheduler plan/state across steps to avoid re-planning.
            scheduler_state = inference_data.get("scheduler_state") or {
                "plan": None,
                "cursor": 0,
                "executed": [],
                "planned_turn": -1,
            }
            if scheduler_state.get("plan") is None or scheduler_state.get("planned_turn") != turn_idx:
                scheduler_state["plan"] = self._run_scheduler_plan(
                    message=current_turn_message,
                    inference_history=inference_data.get(
                        "history", inference_data.get("message", [])
                    ),
                    test_entry_id=test_entry_id,
                )
                scheduler_state["cursor"] = 0
                scheduler_state["executed"] = []
                scheduler_state["planned_turn"] = turn_idx
            scheduler_plan = scheduler_state.get("plan")
            plan_actions = scheduler_plan.actions if scheduler_plan else []
            current_action_idx = min(
                scheduler_state.get("cursor", 0), len(plan_actions) if plan_actions else 0
            )
            if scheduler_plan and plan_actions and current_action_idx < len(plan_actions):
                first_action = plan_actions[current_action_idx]
                action_instruction = self._format_action_prompt(current_action_idx, first_action)
                self._append_scheduler_message(
                    inference_data,
                    action_instruction,
                    role="user",
                    test_entry_id=test_entry_id,
                    turn=turn_idx,
                )
                self._persist_scheduler_log(
                    test_entry_id,
                    {
                        "type": "scheduler_plan_instruction",
                        "turn": turn_idx,
                        "cursor": current_action_idx,
                        "content": action_instruction,
                    },
                )
            inference_data["scheduler_state"] = scheduler_state

            # 更新统一 history 并持久化
            user_history_messages = [
                self._clean_user_for_history(msg) for msg in current_turn_message
            ]
            inference_data["history"].extend(user_history_messages)
            for msg in user_history_messages:
                self._persist_history_line(history_persist_path, msg)

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

            count = 0
            simulator_stop_pending = sim_stop
            pending_history_entries: list[dict] = []
            # Keep a lightweight supervision history for the scheduler to assess progression.
            scheduler_history: list = inference_data.get("scheduler_history", [])

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
                self._persist_scheduler_log(
                    test_entry_id,
                    {
                        "type": "model_response",
                        "turn": turn_idx,
                        "step": count,
                        "model_responses": make_json_serializable(model_responses),
                        "raw": make_json_serializable(model_response_data),
                    },
                )

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
                pending_history_entries.extend(
                    [self.clean_assistant_for_history(msg) for msg in raw_assistant_history]
                )

                # Process the metadata
                current_turn_input_token_count.append(model_response_data["input_token"])
                current_turn_output_token_count.append(model_response_data["output_token"])
                current_turn_latency.append(query_latency)

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

                decoded_model_responses = []
                decoded_has_tool_call = False
                decoded_tool_names: list[str] = []
                # Try decoding the model response
                try:
                    decoded_model_responses = self.decode_execute(model_responses)
                    decoded_has_tool_call = not is_empty_execute_response(
                        decoded_model_responses
                    )
                    for decoded_call in decoded_model_responses:
                        if isinstance(decoded_call, dict):
                            for name in decoded_call.keys():
                                decoded_tool_names.append(name.split("(")[0])
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

                tool_call_executed = False
                supervision = None
                if decoded_has_tool_call:
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
                    for decoded_call, execution_result in zip(
                        decoded_model_responses, execution_results
                    ):
                        tool_history_entries.append(
                            self._tool_result_history_entry(decoded_call, execution_result)
                        )
                    if not tool_history_entries and execution_results:
                        tool_history_entries = [
                            {"role": "tool", "name": "tool_call", "content": str(result)}
                            for result in execution_results
                        ]
                    pending_history_entries.extend(tool_history_entries)

                    for execution_result in execution_results:
                        current_step_inference_log.append(
                            {
                                "role": "tool",
                                "content": execution_result,
                            }
                        )

                # Let scheduler supervise even if no tool call, so it can push guidance.
                supervision = self._run_scheduler_supervision(
                    scheduler_plan,
                    decoded_model_responses if decoded_has_tool_call else model_responses,
                    test_entry_id,
                    state=inference_data.get("scheduler_state"),
                    history=scheduler_history,
                )
                decision_status = supervision.status if supervision else None
                decision_guidance = None
                expected_action = None
                if scheduler_plan and plan_actions and current_action_idx < len(plan_actions):
                    expected_action = plan_actions[current_action_idx]

                # Never mark complete until the full action list is executed/validated.
                def _has_remaining_actions() -> bool:
                    return bool(plan_actions) and current_action_idx < len(plan_actions) - 1

                if not decision_status:
                    if expected_action:
                        expected_tool = getattr(expected_action, "tool", "")
                        if decoded_has_tool_call and expected_tool in decoded_tool_names:
                            decision_status = "continue" if _has_remaining_actions() else "complete"
                        else:
                            decision_status = "redo"
                            decision_guidance = self._format_action_prompt(
                                current_action_idx, expected_action
                            )
                    else:
                        decision_status = "complete"
                # Guard against premature completion when actions remain.
                if decision_status == "complete" and _has_remaining_actions():
                    decision_status = "continue"

                remaining_actions_serialized = []
                if supervision and getattr(supervision, "remaining_actions", None):
                    remaining_actions_serialized = [
                        self._action_to_dict(action) for action in supervision.remaining_actions
                    ]
                self._persist_scheduler_log(
                    test_entry_id,
                    {
                        "type": "scheduler_supervision_decision",
                        "turn": turn_idx,
                        "step": count,
                        "status": decision_status,
                        "remaining_actions": make_json_serializable(remaining_actions_serialized),
                        "assistant_message": getattr(supervision, "assistant_message", None)
                        if supervision
                        else None,
                        "guidance": getattr(supervision, "guidance", None) if supervision else None,
                    },
                )

                if decision_status == "complete":
                    # All actions satisfied; finalize and flush approved history.
                    if supervision and getattr(supervision, "assistant_message", None):
                        pending_history_entries.append(
                            self._clean_user_for_history(
                                {"role": "assistant", "content": supervision.assistant_message}
                            )
                        )
                    if expected_action and scheduler_plan:
                        scheduler_state["executed"].append(self._action_to_dict(expected_action))
                    scheduler_state["cursor"] = 0
                    scheduler_state["plan"] = None
                    scheduler_state["executed"] = []
                    scheduler_state["planned_turn"] = -1
                    _flush_pending_history()
                    tool_call_executed = True
                elif decision_status == "continue":
                    # Current action accepted; move to next planned action.
                    if expected_action and scheduler_plan:
                        scheduler_state["executed"].append(self._action_to_dict(expected_action))
                    scheduler_state["cursor"] = min(current_action_idx + 1, len(plan_actions))
                    current_action_idx = scheduler_state["cursor"]
                    if scheduler_plan and plan_actions and current_action_idx < len(plan_actions):
                        next_action = plan_actions[current_action_idx]
                        guidance_text = (
                            supervision.assistant_message
                            or supervision.guidance
                            or self._format_action_prompt(current_action_idx, next_action)
                        )
                        if guidance_text:
                            self._append_scheduler_message(
                                inference_data,
                                guidance_text,
                                role="user",
                                test_entry_id=test_entry_id,
                                turn=turn_idx,
                                step=count,
                            )
                    print("Scheduler requested next action; repeating step.")
                elif decision_status == "redo":
                    # Action rejected; request redo without advancing action pointer.
                    guidance_text = (
                        decision_guidance
                        or (supervision.assistant_message if supervision else None)
                        or (supervision.guidance if supervision else None)
                    )
                    if guidance_text:
                        self._append_scheduler_message(
                            inference_data,
                            guidance_text,
                            role="user",
                            test_entry_id=test_entry_id,
                            turn=turn_idx,
                            step=count,
                        )
                    print("Scheduler requested redo; repeating step.")
                else:
                    # Unknown status: if no plan/actions, flush; otherwise keep pending for safety.
                    if not plan_actions:
                        _flush_pending_history()
                        if decoded_has_tool_call:
                            tool_call_executed = True

                # Persist scheduler state for debugging/continuity.
                inference_data["scheduler_state"] = scheduler_state
                scheduler_history.append(
                    {
                        "turn": turn_idx,
                        "step": count,
                        "fc_outputs": decoded_model_responses
                        if decoded_has_tool_call
                        else model_responses,
                        "decision": decision_status,
                        "cursor": scheduler_state.get("cursor", 0),
                    }
                )
                inference_data["scheduler_history"] = scheduler_history[-20:]  # cap length
                self._persist_scheduler_log(
                    test_entry_id,
                    {
                        "type": "scheduler_state",
                        "turn": turn_idx,
                        "step": count,
                        "cursor": scheduler_state.get("cursor", 0),
                        "executed": make_json_serializable(scheduler_state.get("executed", [])),
                        "planned_turn": scheduler_state.get("planned_turn", -1),
                        "history_len": len(inference_data.get("scheduler_history", [])),
                    },
                )

                count += 1
                if tool_call_executed:
                    break
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
        # Lazily instantiate scheduler with compiled tools if needed.
        self._ensure_scheduler(test_entry.get("function", []), test_entry)
        # Optional scheduler planning before FC query.
        scheduler_plan = self._run_scheduler_plan(
            message=test_entry.get("question", [[]])[0],
            inference_history=inference_data.get("history", inference_data.get("message", [])),
            test_entry_id=test_entry.get("id", "unknown_id"),
        )
        inference_data = self.add_first_turn_message_FC(
            inference_data, test_entry["question"][0]
        )
        attempt = 0
        final_model_responses = None
        metadata = {}
        last_model_response_data = None

        while attempt < self.scheduler_step_budget:
            api_response, query_latency = self._query_FC(inference_data)

            # Try parsing the model response
            model_response_data = self._parse_query_response_FC(api_response)
            last_model_response_data = model_response_data

            supervision = self._run_scheduler_supervision(
                scheduler_plan,
                model_response_data.get("model_responses"),
                test_entry.get("id", "unknown_id"),
            )

            if not supervision or supervision.status == "complete":
                final_model_responses = model_response_data["model_responses"]
                break

            attempt += 1

        if final_model_responses is None and last_model_response_data:
            final_model_responses = last_model_response_data["model_responses"]
            query_latency = query_latency if "query_latency" in locals() else 0

        # Process the metadata
        if include_input_log:
            metadata["inference_log"] = [
                {
                    "role": "inference_input",
                    "content": inference_data.get("inference_input_log", ""),
                }
            ]
        if last_model_response_data:
            metadata["input_token_count"] = last_model_response_data.get("input_token", 0)
            metadata["output_token_count"] = last_model_response_data.get("output_token", 0)
            metadata["latency"] = query_latency
            if (
                "reasoning_content" in last_model_response_data
                and last_model_response_data["reasoning_content"] != ""
            ):
                metadata["reasoning_content"] = last_model_response_data["reasoning_content"]

        return final_model_responses, metadata

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

    @final
    def write(self, result, result_dir, update_mode=False):
        """
        Persist inference outputs under RESULT_PATH grouped by test category.

        When `update_mode` is True the existing file is re-written with merged content;
        otherwise new entries are appended (while keeping IDs sorted).
        """
        model_name_dir = self.model_name.replace("/", "_")
        model_result_dir = result_dir / model_name_dir
        model_result_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(result, dict):
            result = [result]

        # Collect and format each entry for JSON compatibility
        entries_to_write = [make_json_serializable(entry) for entry in result]

        # Group entries by their `test_category` for efficient file handling
        file_entries = {}
        for entry in entries_to_write:
            test_category = entry["id"].rsplit("_", 1)[0]
            file_name = f"{VERSION_PREFIX}_{test_category}_result.json"
            file_path = model_result_dir / file_name
            file_entries.setdefault(file_path, []).append(entry)

        for file_path, entries in file_entries.items():
            if update_mode:
                # Load existing entries from the file
                existing_entries = {}
                if file_path.exists():
                    existing_entries = {
                        entry["id"]: entry for entry in load_file(file_path)
                    }

                # Update existing entries with new data
                for entry in entries:
                    existing_entries[entry["id"]] = entry

                # Sort entries by `id` and write them back to ensure order consistency
                sorted_entries = sorted(existing_entries.values(), key=sort_key)
                with open(file_path, "w") as f:
                    for entry in sorted_entries:
                        f.write(json.dumps(entry) + "\n")

            else:
                # Normal mode: Append in sorted order
                entries.sort(key=sort_key)
                with open(file_path, "a") as f:
                    for entry in entries:
                        f.write(json.dumps(entry) + "\n")

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
