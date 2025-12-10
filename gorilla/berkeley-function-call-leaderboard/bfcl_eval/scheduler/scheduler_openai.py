from __future__ import annotations

import json
from typing import Any, List, Optional

from bfcl_eval.scheduler.scheduler_base import (
    ActionItem,
    PlanResult,
    SchedulerBase,
    StrategyPlan,
    SupervisionResult,
    serialize_action_items,
)
from bfcl_eval.scheduler import prompts
from openai import OpenAI


class OpenAIScheduler(SchedulerBase):
    """
    OpenAI-backed scheduler implementation.
    Uses planning/supervision prompts to produce strategy + actions and to
    validate FC outputs. Expects the injected `client` to support either
    `responses.create` or `chat.completions.create` with OpenAI-compatible args.
    """

    def __init__(
        self,
        model_api: Any,
        tools: list[Any],
        user_profile: Optional[dict] = None,
        step_budget: int = 5,
        client: Any = None,
    ) -> None:
        super().__init__(model_api, tools, user_profile, step_budget)
        # Client is intentionally not shared with handlers to avoid history pollution.
        self.client = client or OpenAI()
        # Fix default model/params for scheduler LLM.
        self.scheduler_model = "gpt-4.1-2025-04-14"
        self.scheduler_temperature = 0.1

    def plan(self, message: list[dict], history: list[dict]) -> PlanResult:
        """Call OpenAI with the planning prompt and parse the plan."""
        payload = self.build_prompt_init(message, history)
        response_text = self._call_model(prompts.PLANNING_PROMPT, payload)
        return self.parse_plan(response_text)

    def build_prompt_init(
        self, task_message: list[dict], history: list[dict]
    ) -> str:
        payload = {
            "task": task_message,
            "history": history,
            "tools": self.tools,
            "user_profile": self.user_profile,
        }
        return json.dumps(payload, ensure_ascii=False)

    def build_prompt_step(self, body_output: Any, history: list[dict]) -> str:
        payload = {
            "body_output": body_output,
            "history": history,
            "tools": self.tools,
            "user_profile": self.user_profile,
        }
        return json.dumps(payload, ensure_ascii=False)

    def parse_plan(self, response: Any) -> PlanResult:
        parsed = self._parse_json(response)
        strategy = parsed.get("strategy_plan", {}) if isinstance(parsed, dict) else {}
        actions_raw = parsed.get("actions", []) if isinstance(parsed, dict) else []
        return PlanResult(
            strategy_plan=self._to_strategy_plan(strategy),
            actions=self._to_action_items(actions_raw),
            validated_tools=parsed.get("validated_tools"),
            note=parsed.get("note"),
        )

    def supervise(
        self,
        plan_result: PlanResult,
        fc_outputs: Any,
        state: dict | None = None,
        history: list | None = None,
    ) -> SupervisionResult:
        """
        Use the supervision prompt to decide whether the FC outputs complete the plan.
        """
        state = state or {}
        history = history or []
        payload = self.build_prompt_step(
            body_output={
                "planned_strategy": plan_result.strategy_plan.__dict__,
                "planned_actions": serialize_action_items(plan_result.actions),
                "fc_outputs": fc_outputs,
                "state": {
                    "cursor": state.get("cursor"),
                    "executed": serialize_action_items(state.get("executed")),
                },
                "supervision_history": history,
            },
            history=[],
        )
        response_text = self._call_model(prompts.SUPERVISION_PROMPT, payload)
        parsed = self._parse_json(response_text)
        status = parsed.get("status", "continue")
        if status == "complete":
            return SupervisionResult(
                status="complete",
                final_actions=self._to_action_items(parsed.get("final_actions", [])),
                validated_tools=parsed.get("validated_tools") or self._infer_tools(plan_result),
                assistant_message=parsed.get("assistant_message"),
            )
        return SupervisionResult(
            status="continue",
            remaining_actions=self._to_action_items(parsed.get("remaining_actions", [])),
            validated_tools=parsed.get("validated_tools") or self._infer_tools(plan_result),
            guidance=parsed.get("guidance"),
        )

    def _call_model(self, system_prompt: str, user_payload: str) -> str:
        if not self.client:
            raise RuntimeError("OpenAI client not configured for scheduler.")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ]
        # Prefer Responses API if available, else fall back to Chat Completions.
        if hasattr(self.client, "responses"):
            resp = self.client.responses.create(
                model=self.scheduler_model,
                input=messages,
                temperature=self.scheduler_temperature,
            )
            return getattr(resp, "output_text", "") or json.dumps(
                getattr(resp, "output", ""), ensure_ascii=False
            )
        if hasattr(self.client, "chat") and hasattr(self.client.chat, "completions"):
            resp = self.client.chat.completions.create(
                model=self.scheduler_model,
                messages=messages,
                temperature=self.scheduler_temperature,
            )
            return resp.choices[0].message.content
        raise RuntimeError("OpenAI client does not support responses or chat.completions API.")

    @staticmethod
    def _parse_json(response: Any) -> dict:
        if isinstance(response, dict):
            return response
        if not response:
            return {}
        if isinstance(response, str):
            try:
                # Strip code fences if present
                cleaned = response.strip()
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`")
                    cleaned = cleaned.replace("json", "", 1).strip()
                return json.loads(cleaned)
            except Exception:
                return {}
        try:
            return json.loads(str(response))
        except Exception:
            return {}

    @staticmethod
    def _to_strategy_plan(raw: dict) -> StrategyPlan:
        if not isinstance(raw, dict):
            return StrategyPlan()
        return StrategyPlan(
            intention=raw.get("intention"),
            initiative=raw.get("initiative"),
            invocation=raw.get("invocation"),
            confirmation=raw.get("confirmation"),
            transparency=raw.get("transparency", {}),
            info_acquisition=raw.get("info_acquisition", {}),
            error_handling=raw.get("error_handling", {}),
            failure=raw.get("failure", {}),
            presentation=raw.get("presentation"),
        )

    @staticmethod
    def _to_action_items(raw_actions: Any) -> List[ActionItem]:
        items: List[ActionItem] = []
        if not isinstance(raw_actions, list):
            return items
        for entry in raw_actions:
            if isinstance(entry, dict):
                items.append(ActionItem.from_dict(entry))
            elif isinstance(entry, str):
                items.append(ActionItem(tool="message", args={"content": entry}, raw=entry))
        return items

    def _infer_tools(self, plan_result: PlanResult) -> List[str]:
        inferred = []
        for item in plan_result.actions:
            if item.tool and item.tool not in inferred:
                inferred.append(item.tool)
        return inferred
