======= Interaction Tool Instructions ======= 
{
    "confirmation": {
    "silent": {
      "description": "The user prefers an agent to execute actions automatically without requesting confirmation, prioritizing speed and minimal friction, valuing autonomy over explicit control.",
      "trajectory_1_tool": ["Tool(A)"],
      "trajectory_2_tools": ["Tool(A)", "Tool(B)"]
    },
    "batch": {
      "description": "The user prefers an agent to confirm once for a group of related actions before execution, valuing efficiency but still want periodic checkpoints for coordination and quality assurance.",
      "trajectory_1_tool": [],
      "trajectory_2_tools": [""Message_confirmation", "Tool(A)", "Tool(B)"]
    },
    "each": {
      "description": "The user prefers an agent to confirm every individual action before execution, prioritizing safety and situational awareness, preferring to verify each step to prevent unintended outcomes.",
      "trajectory_1_tool": [""Message_confirmation", "Tool(A)"],
      "trajectory_2_tools": [
        "Message_confirmation",
        "Tool(A)",
        "Message_confirmation",
        "Tool(B)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },


  "transparency_tool_choice": {
    "low": {
      "description": "The user prefers an agent to proceed with tool selection and execution silently, without revealing its reasoning or notifying the user in advance, prioritizing efficiency and smooth workflow over interpretability, trusting the agent’s reasoning implicitly.",
      "trajectory": ["Tool(A)"]
    },
    "medium": {
      "description": "The user prefers an agent to briefly communicates which tool or method will be used, without waiting for the user to confirm. Seeking a balance between enough context to stay informed without excesssive cognitive load.",
      "trajectory": ["Message_tool_invocation", "Tool(A)"]
    },
    "high": {
      "description": "The user prefers an agent to explicitly explains both its tool choice and the underlying reasoning or decision logic before execution, valuing interpretability, accountability, and shared reasoning.",
      "trajectory": [
        "Message_tool_invocation",
        "Message_tool_invocation_logic",
        "Tool(A)"
      ]
    },
      "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },


  "transparency_parameter_choice": {
    "low": {
      "description": "The user prefers an agent to execute the tool without displaying its parameter selections or reasoning, valuing speed and automation, trusting the system to choose appropriate parameters without manual review.",
      "trajectory": ["Tool(A)"]
    },
    "medium": {
      "description": "The users want awareness of parameter choices for orientation, but prefer to avoid cognitive overload.",
      "trajectory": ["Message_display_params", "Tool(A)"]
    },
    "high": {
      "description": "The user prefers an agent to explicitly displays both the selected parameters and the reasoning behind each choice before execution, valuing precision, interpretability, and verification of configuration details.",
      "trajectory": [
        "Message_display_params",
        "Message_display_params_logic",
        "Tool(A)"
      ]
    },
      "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },



  "presentation": {
    "compact": {
      "description": "When receiving results, the user prefers the agent to present information in a concise and sequential manner, valuing enabling faster comprehension without overwhelming detail.",
      "trajectory": ["Tool(A)", "Message_show_sequential_output"]
    },
    "layered": {
      "description": "When receiving results, the user prefers the agent to present information in a layered or expanded format, with gradual elaboration, revealing details progressively, from summary to detailed justification, valuing deeper understanding and reflective assessment.",
      "trajectory": ["Tool(A)", "Message_show_layered_presentation"]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  }

  "information_collection": {
    "gradual": {
      "description": "The user prefers the agent to gather required information through incremental, stepwise requests—filling in missing pieces as needed, and not demanding everything upfront.",
      "trajectory": [
        "Message_information_seeking",
        "Message_information_seeking",
        "Tool(A)"
      ]
    },
    "upfront": {
      "description": "The user prefers the agent to ask for all required information in a single, comprehensive request before proceeding, minimizing back-and-forth questioning.",
      "trajectory": [
        "Message_information_seeking",
        "Tool(A)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "disambiguation": {
    "gradual": {
      "description": "The user prefers clarifications to arrive incrementally rather than a large upfront list.",
      "trajectory": [
        "Message_disambiguation",
        "Message_disambiguation",
        "Tool(A)"
      ]
    },
    "upfront": {
      "description": "The user prefers all ambiguity is resolved in one bundled clarification request to avoid repeated interruptions.",
      "trajectory": [
        "Message_disambiguation",
        "Tool(A)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "source_transparency": {
    "high": {
      "description": "The user wants sources cited and rejects opaque answers; the agent must explicitly present the provenance of information, e.g., via a source report after tool execution.",
      "trajectory": [
        "Tool(A)",
        "Message_source_report"
      ]
    },
    "low": {
      "description": "The user prefers answers without source exposition unless requested; the agent focuses on concise, direct results rather than surfacing sources.",
      "trajectory": [
        "Tool(A)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "tool_abortion": {
    "stop": {
      "description": "On failure, the user wants the workflow to halt instead of continuing. If a tool call fails, the agent should abort remaining actions and explicitly signal task abortion.",
      "trajectory": [
        "Tool(A - Fail)",
        "Message_tool_abort"
      ]
    },
    "continue": {
      "description": "On partial failure, the user wants remaining subtasks to continue. Failures do not halt the workflow; the agent should proceed with other available actions.",
      "trajectory": [
        "Tool(A - Fail)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "chain_execution": {
    "parallel": {
      "description": "The user prefers parallel execution for speed when tasks are independent. Agent should combine multiple low-dependency actions in the same turn as a unified intent.",
      "trajectory": [
        ["Tool(A)", "Tool(B)"],
        "Message_show_output"
      ]
    },
    "sequential": {
      "description": "The user prefers stepwise execution with intermediate visibility. Agent should perform actions in order, providing intermediate feedback after each.",
      "trajectory": [
        "Tool(A)",
        "Message_show_output",
        "Tool(B)",
        "Message_show_output"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "tool_switch": {
    "high_agency": {
      "description": "Wants automatic tool switching on failure without asking. If a tool fails, the agent should seamlessly switch to an alternative tool and continue without user interruption.",
      "trajectory": [
        "Tool(A1 - Fail)",
        "Tool(A2)"
      ]
    },
    "low_agency": {
      "description": "Wants to be informed and approve before switching tools. If a tool fails, the agent should notify the user that a tool switch is necessary, then proceed only after this notification.",
      "trajectory": [
        "Tool(A1 - Fail)",
        "Message_tool_switch_notice",
        "Tool(A2)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "error_retry": {
    "silent": {
      "description": "Prefers silent, autonomous retries unless failures persist. The agent should attempt failed actions again automatically without notifying the user unless repeated failure occurs.",
      "trajectory": [
        "Tool(A - Fail)",
        "Tool(A - Retry)"
      ]
    },
    "escalation": {
      "description": "Wants errors surfaced and confirmation before retrying. The agent should notify the user of the error and ask or confirm before attempting a retry.",
      "trajectory": [
        "Tool(A - Fail)",
        "Message_tool_failure_notice",
        "Tool(A - Retry)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "error_discovery": {
    "brief": {
      "description": "Wants minimal failure notice; rejects verbose diagnostics. When the agent encounters a failure, it should flag the failure succinctly without extra explanation.",
      "trajectory": [
        "Tool(A - Fail)",
        "Message_tool_failure_notice"
      ]
    },
    "detail": {
      "description": "Wants reasoning/root cause when errors occur. The agent should not only flag the failure, but also provide reasoning, root cause, or remedial suggestions.",
      "trajectory": [
        "Tool(A - Fail)",
        "Message_tool_failure_notice",
        "Message_tool_failure_logic"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "tool_invocation": {
    "single": {
      "description": "Prefers picking the best single tool/option over exploring many. The agent should confidently select and invoke the most suitable tool without trying multiple alternatives.",
      "trajectory": [
        "Tool(A1 or A2)"  // Best-choice tool, pick one
      ]
    },
    "multiple": {
      "description": "When available, prefers running multiple options to compare outcomes. The agent should run several relevant tools and provide results for comparison.",
      "trajectory": [
        "Tool(A1)",
        "Tool(A2)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  "tool_initiative": {
    "proactive": {
      "description": "Wants the agent to act within scope without waiting for every nudge. The agent should proactively call tools when the goal is clear, without pausing for explicit prompts.",
      "trajectory": [
        "Tool(A)" 
      ]
    },
    "reactive": {
      "description": "Wants the agent to wait for explicit go-ahead before acting. Tool calls should only happen when the user's request directly includes or clearly instructs action.",
      "trajectory": [
        "Tool(A)"
      ]
    },
    "null": {
      "description": "When the user didn’t show any specific preferences."
    }
  },
  
}

