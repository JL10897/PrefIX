# LLM Scheduler Refactor Plan (Draft, cleaned)

This document captures the refactor understanding and implementation plan.

## What I heard
- Introduce a scheduler abstraction mediating between simulator + model and the executor.
- BaseHandler becomes orchestration-only: it invokes `scheduler.plan(history, user_message)` and feeds the returned plan into the existing executor.
- Scheduler is model-family specific. Add `scheduler/` package with:
  - `scheduler_base.py` defining `SchedulerBase`.
  - `scheduler_openai.py`, `scheduler_claude.py`, `scheduler_llama.py` implementing `plan`.
- `SchedulerBase.plan(message, history)` returns:
  - `strategy_plan`: confirmation/initiative/batching, etc.
  - `actions`: ordered tool invocations (tool name + args).
- BaseHandler does not care which model is used; it calls `scheduler.plan`, executes `actions` via FC executor, and surfaces text.
- History/state storage likely needs renaming/restructuring to support plans and execution logs.

## Updated approach (per clarifications)
1. Add `bfcl_eval/scheduler/` package (`__init__.py`, `scheduler_base.py`, `scheduler_openai.py`, `scheduler_claude.py`, `scheduler_llama.py`).
2. `SchedulerBase.plan(message, history)` returns `strategy_plan` and `actions` (no `text_to_user` requirement). `strategy_plan` encodes interaction strategy; `actions` is an ordered sequence of action/tool intents (interaction + tool functions).
3. Each scheduler wraps its own model client (no shared handler clients/history) and implements `build_prompt` → `chat` → `parse_plan`.
4. BaseHandler injects a scheduler (via factory/flag). Loop: gather history → `scheduler.plan` → FC executor carries out `strategy_plan`/`actions` → scheduler validates FC outputs vs plan → when complete, scheduler returns consolidated tool calls to handler for parse/state/log. Scheduler is “brain”, FC executor is “body”.
5. FC executor interface extends to accept strategy hints and action bundle. Scheduler may hold partial batches until plan-complete before emitting to handler.
6. History/state storage renamed/restructured for planner outputs, executor attempts, scheduler validation (e.g., `plan`, `actions_pending`, `actions_executed`, `strategy_plan`, `scheduler_validation`).

## Confirmed design
- `strategy_plan` schema (TypedDict/dataclass):
  ```
  {
    "intention": "string | null",
    "initiative": "proactive | reactive | null",
    "invocation": "single | multi | null",
    "confirmation": "silent | batch | each | null",
    "transparency": {
      "tool_choice": "low | medium | high | null",
      "param_choice": "low | medium | high | null",
      "source": "low | high | null"
    },
    "info_acquisition": {
      "params": "gradual | upfront | null",
      "intention": "gradual | upfront | null"
    },
    "error_handling": {
      "explanation": "brief | detail | null",
      "retry": "silent | escalation | hybrid | null"
    },
    "failure": {
      "abortion": "stop | unstop | null",
      "switch_agency": "high | low | null"
    },
    "presentation": "compact | layered | null"
  }
  ```
- `actions` format: dict `{tool: str, args: dict}` and strings for interaction-type calls (e.g., message_tool_abort); FC model supplies string content; tool list (action + interaction) comes from compiled func_docs provided to scheduler.
- Sequencing: ordered with dependencies (e.g., confirmation before guarded tool). Scenario-specific; scheduler enforces.
- No strategy-only plans: confirmation/clarification is an action; every plan has ≥1 action.
- FC shortfall/mismatch: scheduler re-issues to FC “body” until plan satisfied or limits hit.
- Success/abort: bounded retries; if exhausted, return error; abort signals handler task cannot complete.
- Multi-tool per turn: scheduler may accumulate multiple FC executions and only yield to handler after validation.
- History to plan: scheduler sees the same inputs FC would see; plus its own dialogue/progress with FC is persisted separately.
- Tool-call IDs: flow from func_docs/model output through scheduler → executor → handler.
- Location: scheduler lives under `bfcl_eval/eval_checker`; tests/docs colocated there.

## Outstanding implementation items
- Step budget: default max 5 scheduler↔FC exchanges per turn before failing.
- Persistence: new per-turn scheduler log file (one scheduler flow = one file), separate from existing history_persist_path.
- Scheduler prompt: design prompt that produces initial `strategy_plan + actions` and supervises FC until completion/abort; includes text-from-FC filtering module before surfacing to user, mainly aggregating the executions that will be/have been done in this turn.
- Handler flow: BaseHandler → scheduler.plan → FC executor loop (with retries/validation) → scheduler aggregates/filters → handler logs/parses/returns.

## Prompt design requirements
- init_planning_prompt (first turn): input = task description, specific user–AI history (placeholder for now), compiled tool list; output = `strategy_plan` v1.
- step_planning_prompt (each turn thereafter): input = latest FC output (body), current tool list; output includes:
  - `strategy_plan` for the current round.
  - `actions` supervision: executable sequence (scheduler’s decisions). Compare FC outputs already given; if misaligned, require FC to correct/complete until actions are done or step budget is hit.
  - `validated_tools`: tool usage check/fill/fix iterations for this round in FC model (scheduler only thinks/speaks, no direct execution).

## Implementation plan by file
- `bfcl_eval/scheduler/scheduler_base.py`: define `SchedulerBase`, TypedDict/dataclass schemas for `StrategyPlan`, `ActionItem`, `PlanResult`, and abstract `plan` plus shared helpers (prompt build hooks, logging hooks).
- `bfcl_eval/scheduler/scheduler_openai.py`: OpenAI-specific scheduler, owns its client, implements `build_prompt` (init/step), `plan`, `parse_plan`.
- `bfcl_eval/model_handler/base_handler.py`: accept/inject scheduler via factory/config; route FC execution through scheduler (brain) before handler processes results; wire in strategy/action bundle to FC executor; adjust history handling to include scheduler logs and per-turn scheduler file path.
- `bfcl_eval/eval_checker/llm_scheduler_f.md`: keep updated design + mapping (this file).
