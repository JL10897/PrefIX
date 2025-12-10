
You will modify the BFCL BaseHandler (multi-turn FC path only) to fix the following issues.
Do not modify the user simulator itself.
Do not modify evaluator internal modules such as execute_multi_turn_func_call.

All changes must be **minimal, backward compatible, and safe**.

============================================================

# **1. Fix holdout-function logic in FC multi-turn**

Problem:
In simulator mode, `current_turn_message` is never empty because simulator always produces a user message.
Therefore this assertion always fails:

```
assert len(current_turn_message) == 0
```

Fix:

* Remove the assertion entirely.
* Apply holdout logic by **ignoring** simulator’s user message for that turn and replacing it with the default additional-function prompt.
* Behavior should match original BFCL design:

```
current_turn_message = [{
    "role": "user",
    "content": DEFAULT_USER_PROMPT_FOR_ADDITIONAL_FUNCTION_FC
}]
```

* Do not rely on the simulator output for holdout turns.

============================================================

# **2. Add missing import of Path**

At the top of BaseHandler, ensure:

```
from pathlib import Path
```

============================================================

# **3. Fix step-level break logic in FC mode**

Current behavior:
Step loop breaks whenever the decoded tool call is empty.
This incorrectly ends a turn when the model replies normally such as:
"Sure, what else do you need?"
even though no tool call was intended.

Fix requirements:

Replace this logic:

```
if is_empty_execute_response(decoded):
    break
```

with:

### New rule:

**Only break the step-loop if at least one of the following is true:**

1. The model emitted a tool call that was executed, AND you want to stop to start a new turn.
2. The model output could not be decoded AND no tool call exists.
3. The simulator has already signaled `<END_SIMULATION>`.

### Remove the assumption that empty decoded response always ends the turn.

You must allow:

* assistant free-text messages
* multi-step agent messages without tool calls

to continue accumulating in the same turn without forcing break.

### Recommended implementation:

After decoding:

```
if decoded_has_tool_call(decoded):
    # run tool execution, then break the step loop
else:
    # no tool call
    # continue step loop unless MAXIMUM_STEP_LIMIT is hit
```

Leave a maximum safety limit: if more than MAXIMUM_STEP_LIMIT steps, force quit as before.

============================================================

# **4. Fix history persistence to be append-based, not rewrite**

Current logic rewrites the entire history JSON file every step.
This is dangerous for long histories and can corrupt state.

Fix:

* Replace `write_text(json.dumps(...))` with append operations.
* File format should be **JSON lines** (one JSON object per line).
* On load, read all lines and parse into a list.

Requirements:

### When writing:

```
with open(history_persist_path, "a", encoding="utf8") as f:
    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
```

Do not rewrite entire file.

### When loading:

Already safe. No change needed.

============================================================

# **5. Record simulator turns into metadata**

Add to final metadata:

```
metadata["simulator_turns"] = number_of_turns_generated_by_simulator
```

Where this count increments whenever BaseHandler calls:

```
self.user_simulator.generate_user_turn(...)
```

or generate_next_turn depending on your variant.

============================================================

# **6. Clarify relationship between inference_data["message"] and inference_data["history"]**

Implement the following invariant:

### 6.1 inference_data["message"]

* This is the **model input context**.
* Contains raw user messages, raw assistant messages, complete tool_call dictionaries, and tool outputs in the same shape produced by the evaluator.
* DO NOT clean or post-process content.

### 6.2 inference_data["history"]

* This is the **simulator-only canonical trajectory**.
* Contains cleaned natural language messages only.
* Assistant messages must be cleaned from JSON, tool blocks, function_call metadata.
* Tool results must use a structured compact representation:

  ```
  {"role": "tool", "name": <tool_name>, "content": <short_text>}
  ```

### 6.3 Required updates to FC methods

You must modify:

* `_add_next_turn_user_message_FC`
* `_add_assistant_message_FC`
* `_add_execution_results_FC`

So that:

```
inference_data["message"] receives full raw content
inference_data["history"] receives cleaned content (that simulate what a user sees in the front-end)
```

Add helper:

```
def clean_assistant_for_history(raw):
    # strip tool_call metadata, keep only natural language
```

============================================================

# **7. Ensure assistant messages always go into history**

In `_add_assistant_message_FC`, after adding to message:

```
history.append(clean_assistant_for_history(raw_assistant_message))
persist_history_line(...)
```

============================================================

# **8. Ensure tool execution results are recorded in history**

After execution:

```
history.append({"role": "tool", "name": <...>, "content": <short summary>})
persist_history_line(...)
```

============================================================

# **Deliverables**

Modify BaseHandler so that:

* FC step-loop no longer incorrectly breaks on empty decoded responses
* Holdout logic works under simulator mode
* History persistence is append-based
* Raw-vs-clean separation is correct
* Metadata includes simulator turn count
* Import errors are resolved

All patches must be minimal and must not change evaluator behavior beyond the fixes requested.

