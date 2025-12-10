from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class SchedulerProtocol(Protocol):
    """
    A lightweight protocol to allow BaseHandler to depend on schedulers without
    importing concrete implementations. Concrete schedulers should inherit from
    SchedulerBase to reuse helpers and type hints.
    """

    def plan(self, message: list[dict], history: list[dict]) -> "PlanResult":
        ...


@dataclass
class StrategyPlan:
    intention: Optional[str] = None
    initiative: Optional[str] = None  # proactive | reactive
    invocation: Optional[str] = None  # single | multi
    confirmation: Optional[str] = None  # silent | batch | each
    transparency: Dict[str, Optional[str]] = field(
        default_factory=lambda: {
            "tool_choice": None,
            "param_choice": None,
            "source": None,
        }
    )
    info_acquisition: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"params": None, "intention": None}
    )
    error_handling: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"explanation": None, "retry": None}
    )
    failure: Dict[str, Optional[str]] = field(
        default_factory=lambda: {"abortion": None, "switch_agency": None}
    )
    presentation: Optional[str] = None


@dataclass
class ActionItem:
    tool: str
    args: Dict[str, Any] | None = None
    raw: Optional[str] = None  # for interaction-type strings

    def to_dict(self) -> Dict[str, Any]:
        """
        Return a JSON-serializable representation of the action.
        """
        return {"tool": self.tool or "", "args": self.args, "raw": self.raw}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionItem":
        """
        Reconstruct an ActionItem from a plain dictionary. Missing keys default to empty strings/None.
        """
        if not isinstance(data, dict):
            return cls(tool=str(data))
        return cls(tool=str(data.get("tool", "")), args=data.get("args"), raw=data.get("raw"))

    @staticmethod
    def to_serializable(action: Any) -> Dict[str, Any]:
        """
        Best-effort conversion of any action-like object to a JSON-safe dict.
        """
        if isinstance(action, ActionItem):
            return action.to_dict()
        if isinstance(action, dict):
            return {
                "tool": action.get("tool", ""),
                "args": action.get("args"),
                "raw": action.get("raw"),
            }
        return {
            "tool": getattr(action, "tool", ""),
            "args": getattr(action, "args", None),
            "raw": getattr(action, "raw", None),
        }


def serialize_action_items(actions: Any) -> list[Dict[str, Any]]:
    """
    Normalize a list of action-like objects into plain dictionaries for JSON serialization.
    """
    if not actions:
        return []
    serialized: list[Dict[str, Any]] = []
    for action in actions:
        serialized.append(ActionItem.to_serializable(action))
    return serialized


@dataclass
class PlanResult:
    strategy_plan: StrategyPlan
    actions: List[ActionItem]
    validated_tools: Optional[List[str]] = None
    note: Optional[str] = None


@dataclass
class SupervisionResult:
    status: str  # "complete" | "continue"
    remaining_actions: List[ActionItem] = field(default_factory=list)
    final_actions: List[ActionItem] = field(default_factory=list)
    validated_tools: Optional[List[str]] = None
    assistant_message: Optional[str] = None
    guidance: Optional[str] = None


class SchedulerBase:
    """
    Base class for schedulers. It owns a model_api/client, the tool list, and an
    optional user_profile. Subclasses implement prompt construction, chat, and
    plan parsing.
    """

    def __init__(
        self,
        model_api: Any,
        tools: list[Any],
        user_profile: Optional[dict] = None,
        step_budget: int = 5,
    ) -> None:
        self.model_api = model_api
        self.tools = tools
        self.user_profile = user_profile or {}
        self.step_budget = step_budget

    def plan(self, message: list[dict], history: list[dict]) -> PlanResult:
        raise NotImplementedError

    # Helper hook for subclasses; not used by BaseHandler directly.
    def build_prompt_init(
        self, task_message: list[dict], history: list[dict]
    ) -> dict | str:
        raise NotImplementedError

    def build_prompt_step(
        self, body_output: Any, history: list[dict]
    ) -> dict | str:
        raise NotImplementedError

    def parse_plan(self, response: Any) -> PlanResult:
        raise NotImplementedError

    def supervise(
        self,
        plan_result: PlanResult,
        fc_outputs: Any,
        state: Optional[dict] = None,
        history: Optional[list] = None,
    ) -> SupervisionResult:
        """
        Default supervision: if planned actions are empty or FC produced at least
        as many outputs as planned, mark complete; otherwise request continuation.
        Subclasses can override with LLM-based validation.
        """
        planned_actions = plan_result.actions if plan_result else []
        produced_count = 0
        if isinstance(fc_outputs, list):
            produced_count = len(fc_outputs)
        if not planned_actions or produced_count >= len(planned_actions):
            return SupervisionResult(
                status="complete",
                final_actions=planned_actions or [],
                validated_tools=plan_result.validated_tools if plan_result else None,
            )
        return SupervisionResult(
            status="continue",
            remaining_actions=planned_actions[produced_count:],
            validated_tools=plan_result.validated_tools if plan_result else None,
        )
