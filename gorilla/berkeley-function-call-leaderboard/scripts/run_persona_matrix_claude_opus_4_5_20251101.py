#!/usr/bin/env python3
"""
Run bfcl_eval generate across all personas with/without interaction history.
This variant targets model: claude-opus-4-5-20251101-FC.
"""

import asyncio
import datetime
import itertools
from pathlib import Path

PERSONAS = [
    "Each Confirmation",
    "Silent Confirmation",
    "Medium Tool Transparency",
    "Low Tool Transparency",
    "High Tool Transparency",
    "Low Parameter Transparency",
    "Medium Parameter Transparency",
    "High Parameter Transparency",
    "Compact Presentation",
    "Layered Presentation",
    "Info Collect Gradual",
    "Info Collect Upfront",
    "Disambiguation Gradual",
    "Disambiguation Upfront",
    "Source Transparency High",
    "Source Transparency Low",
    "Tool Abortion Stop",
    "Tool Abortion Continue",
    "Chain Parallel",
    "Chain Sequential",
    "Tool Switch High Agency",
    "Tool Switch Low Agency",
    "Error Retry Silent",
    "Error Retry Escalation",
    "Error Discovery Brief",
    "Error Discovery Detail",
    "Confirmation Batch",
    "Tool Invocation Single",
    "Tool Invocation Multiple",
    "Tool Initiative Proactive",
    "Tool Initiative Reactive",
]

TEST_CATEGORY = "multi_turn_long_context"
INPUT_FLAGS = ["--test-category", TEST_CATEGORY]
CONCURRENCY = 2

BASE_CMD = [
    "<PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python",
    "-m",
    "bfcl_eval",
    "generate",
    "--model",
    "claude-opus-4-5-20251101-FC",
] + INPUT_FLAGS

FLAG_VARIANTS = [[], ["--no-interaction-history"]]

PROCESSING_DIR = Path(
    "<PROJECT_ROOT>/Desktop/Desktop - ADUAED19365LPMX/Agent_IX_Personalization/Processing"
)
REQUIRE_REWRITE = True

PERSONA_SUFFIX_OVERRIDES = {
    "silent_confirmation": "silent",
    "medium_tool_transparency": "tool_medium",
    "low_tool_transparency": "tool_low",
    "high_tool_transparency": "tool_high",
    "low_parameter_transparency": "param_low",
    "medium_parameter_transparency": "param_medium",
    "high_parameter_transparency": "param_high",
    "compact_presentation": "presentation_compact",
    "layered_presentation": "presentation_layered",
    "each_confirmation": "each_confirmation",
    "info_collect_gradual": "info_collect_gradual",
    "info_collect_upfront": "info_collect_upfront",
    "disambiguation_gradual": "disambiguation_gradual",
    "disambiguation_upfront": "disambiguation_upfront",
    "source_transparency_high": "source_high",
    "source_transparency_low": "source_low",
    "tool_abortion_stop": "tool_abortion_stop",
    "tool_abortion_continue": "tool_abortion_continue",
    "chain_parallel": "chain_parallel",
    "chain_sequential": "chain_sequential",
    "tool_switch_high_agency": "tool_switch_high_agency",
    "tool_switch_low_agency": "tool_switch_low_agency",
    "error_retry_silent": "error_retry_silent",
    "error_retry_escalation": "error_retry_escalation",
    "error_discovery_brief": "error_discovery_brief",
    "error_discovery_detail": "error_discovery_detail",
    "confirmation_batch": "confirmation_batch",
    "tool_invocation_single": "tool_invocation_single",
    "tool_invocation_multiple": "tool_invocation_multiple",
    "tool_initiative_proactive": "tool_initiative_proactive",
    "tool_initiative_reactive": "tool_initiative_reactive",
}

def persona_to_suffix(persona: str) -> str:
    normalized = persona.strip().lower().replace(" ", "_")
    return PERSONA_SUFFIX_OVERRIDES.get(normalized, normalized)

def rewrite_path_for_persona(persona: str) -> Path:
    suffix = persona_to_suffix(persona)
    filename = f"BFCL_v3_{TEST_CATEGORY}_rewrite_filled_{suffix}.json"
    return PROCESSING_DIR / filename


async def worker(queue: asyncio.Queue):
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        persona, extra = item
        cmd = BASE_CMD + ["--simulator-persona", persona] + extra
        start = datetime.datetime.now().isoformat(timespec="seconds")
        print(f"[{start}] start {' '.join(cmd)}", flush=True)
        proc = await asyncio.create_subprocess_exec(*cmd)
        rc = await proc.wait()
        end = datetime.datetime.now().isoformat(timespec="seconds")
        print(f"[{end}] done persona={persona} flags={extra} rc={rc}", flush=True)
        queue.task_done()


async def main():
    queue: asyncio.Queue[tuple[str, list[str]]] = asyncio.Queue()
    for persona, extra in itertools.product(PERSONAS, FLAG_VARIANTS):
        if REQUIRE_REWRITE:
            path = rewrite_path_for_persona(persona)
            if not path.exists():
                print(f"[skip] rewrite file missing for persona={persona}: {path}", flush=True)
                continue
        await queue.put((persona, extra))
    workers = [asyncio.create_task(worker(queue)) for _ in range(CONCURRENCY)]
    await queue.join()
    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)


if __name__ == "__main__":
    asyncio.run(main())
