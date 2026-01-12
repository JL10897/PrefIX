# Preference Interaction History Mapping (fill in details)

Use this table to keep a single source of truth for persona → suffix → history file. The suffix is what `_persona_to_history_suffix` produces; the file must live in this directory as `interaction_history_<suffix>.txt`.

| Persona name (CLI `--simulator-persona`) | Accepted aliases / notes | History suffix (`<suffix>`) | File name | Behavior summary |
| ---------------------------------------- | ------------------------ | --------------------------- | --------- | ---------------- |
| Each Confirmation | each_confirmation | each_confirmation | Interaction_history_each_confirmation.txt | Confirms every tool call |
| Silent Confirmation | silent_confirmation | silent | interaction_history_silent.txt | Runs without asking |
| Medium Tool Transparency | tool_medium | tool_medium | interaction_history_tool_medium.txt | Brief tool heads-up, no gate |
| Low Tool Transparency | tool_low | tool_low | interaction_history_tool_low.txt | No tool narration |
| High Tool Transparency | tool_high | tool_high | interaction_history_tool_high.txt | Explicit tool + rationale before acting |
| Low Parameter Transparency | param_low | param_low | interaction_history_param_low.txt | Hides params |
| Medium Parameter Transparency | param_medium | param_medium | interaction_history_param_medium.txt | Light param visibility |
| High Parameter Transparency | param_high | param_high | interaction_history_param_high.txt | Shows params + rationale |
| Compact Presentation | presentation_compact | presentation_compact | interaction_history_presentation_compact.txt | Concise outputs |
| Layered Presentation | presentation_layered | presentation_layered | interaction_history_presentation_layered.txt | Summary then detail |
| Info Collect Gradual | info_collect_gradual | info_collect_gradual | interaction_history_info_collect_gradual.txt | Collects missing info stepwise |
| Info Collect Upfront | info_collect_upfront | info_collect_upfront | interaction_history_info_collect_upfront.txt | Asks all required info upfront |
| Disambiguation Gradual | disambiguation_gradual | disambiguation_gradual | interaction_history_disambiguation_gradual.txt | Clarifies intent incrementally |
| Disambiguation Upfront | disambiguation_upfront | disambiguation_upfront | interaction_history_disambiguation_upfront.txt | Bundled disambiguation |
| Source Transparency High | source_high | source_high | interaction_history_source_high.txt | Demands cited sources |
| Source Transparency Low | source_low | source_low | interaction_history_source_low.txt | Prefers no source narration |
| Tool Abortion Stop | tool_abortion_stop | tool_abortion_stop | interaction_history_tool_abortion_stop.txt | Halt on failure |
| Tool Abortion Continue | tool_abortion_continue | tool_abortion_continue | interaction_history_tool_abortion_continue.txt | Continue other subtasks after failure |
| Chain Parallel | chain_parallel | chain_parallel | interaction_history_chain_parallel.txt | Parallel tool runs |
| Chain Sequential | chain_sequential | chain_sequential | interaction_history_chain_sequential.txt | Step-by-step tool runs |
| Tool Switch High Agency | tool_switch_high_agency | tool_switch_high_agency | interaction_history_tool_switch_high_agency.txt | Auto-switch tools |
| Tool Switch Low Agency | tool_switch_low_agency | tool_switch_low_agency | interaction_history_tool_switch_low_agency.txt | Ask before switching tools |
| Error Retry Silent | error_retry_silent | error_retry_silent | interaction_history_error_retry_silent.txt | Silent retry on failure |
| Error Retry Escalation | error_retry_escalation | error_retry_escalation | interaction_history_error_retry_escalation.txt | Notify and confirm before retry |
| Error Discovery Brief | error_discovery_brief | error_discovery_brief | interaction_history_error_discovery_brief.txt | Short failure notice |
| Error Discovery Detail | error_discovery_detail | error_discovery_detail | interaction_history_error_discovery_detail.txt | Failure notice with reasoning |
| Confirmation Batch | confirmation_batch | confirmation_batch | interaction_history_confirmation_batch.txt | One confirmation for grouped actions |
| Tool Invocation Single | tool_invocation_single | tool_invocation_single | interaction_history_tool_invocation_single.txt | Pick one best tool/option |
| Tool Invocation Multiple | tool_invocation_multiple | tool_invocation_multiple | interaction_history_tool_invocation_multiple.txt | Explore multiple options |
| Tool Initiative Proactive | tool_initiative_proactive | tool_initiative_proactive | interaction_history_tool_initiative_proactive.txt | Acts within scope without nudges |
| Tool Initiative Reactive | tool_initiative_reactive | tool_initiative_reactive | interaction_history_tool_initiative_reactive.txt | Waits for explicit go-ahead |

Tips:
- If you pass `--interaction-history-suffix`, it overrides the persona→suffix mapping and directly looks for `interaction_history_<suffix>.txt`.
- If a persona is not listed here, the code lowercases it, replaces spaces with underscores, and uses that as the suffix. Add it to the table to avoid surprises.
- Keep file names and suffixes in sync; mismatches will cause the loader to fall back to the default history.
