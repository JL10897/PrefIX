import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

try:
    import openai  # type: ignore
except ImportError:
    openai = None

try:
    import google.generativeai as genai  # type: ignore
except ImportError:
    genai = None


HISTORY_PATH_DEFAULT = os.path.join(os.path.dirname(__file__), "history.json")
ENV_PATH_DEFAULT = os.path.join(os.path.dirname(__file__), ".env")


def load_history(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt() -> str:
    return "I am going to Guangzhou next week and tell me the weather."


def load_env_file(path: str) -> None:
    """Load key=value pairs from a .env file if present (no external dependency)."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "weather_primary",
                "description": "Get baseline weather forecast for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string", "description": "City and country"},
                        "date_range": {
                            "type": "string",
                            "description": "Human readable dates, e.g., next week",
                        },
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "weather_backup",
                "description": "Secondary weather provider mirroring primary coverage.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "date_range": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "weather_forecast_plus",
                "description": "Third weather source focusing on extended outlook and precipitation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "date_range": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "hotel_search",
                "description": "Search for hotels in the target city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "check_in": {"type": "string"},
                        "check_out": {"type": "string"},
                        "guests": {"type": "integer", "description": "Number of guests"},
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rental_car_search",
                "description": "Find rental car options.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                        "pickup_date": {"type": "string"},
                        "dropoff_date": {"type": "string"},
                        "vehicle_class": {"type": "string"},
                    },
                    "required": ["location"],
                },
            },
        },
    ]


def openai_messages(history: List[Dict[str, str]], user_prompt: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def gemini_messages(history: List[Dict[str, str]], user_prompt: str) -> List[Dict[str, Any]]:
    role_map = {"assistant": "model", "user": "user"}
    messages: List[Dict[str, Any]] = []
    for msg in history:
        messages.append({"role": role_map.get(msg["role"], "user"), "parts": [msg["content"]]})
    messages.append({"role": "user", "parts": [user_prompt]})
    return messages


def print_tool_attempts_openai(response: Any) -> None:
    # Support both OpenAI v1.x client objects and legacy response dicts.
    choice = None
    tool_calls = None
    content = None
    if hasattr(response, "choices"):  # v1 client
        choice = response.choices[0].message
        content = choice.content
        tool_calls = choice.tool_calls
    else:  # legacy dict response
        choice = response["choices"][0]["message"]
        content = choice.get("content")
        tool_calls = choice.get("tool_calls")

    print("\n[OpenAI] Raw message content:\n", content)
    if not tool_calls:
        print("[OpenAI] No tool calls found.")
        return

    print("\n[OpenAI] Tool calls:")
    for call in tool_calls:
        if hasattr(call, "function"):  # v1 object
            fn = call.function
            print(f"- name: {fn.name}, arguments: {fn.arguments}")
        else:
            fn = call.get("function", {})
            print(f"- name: {fn.get('name')}, arguments: {fn.get('arguments')}")


def gemini_function_declarations(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    declarations: List[Dict[str, Any]] = []
    for tool in tools:
        fn = tool["function"]
        declarations.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            }
        )
    return declarations


def print_tool_attempts_gemini(response: Any) -> None:
    print("\n[Gemini] Raw candidate content:\n", response.candidates[0].content)
    calls = []
    for part in response.candidates[0].content.parts:
        if hasattr(part, "function_call") and part.function_call:
            calls.append(part.function_call)
    if not calls:
        print("[Gemini] No function calls found.")
        return
    print("\n[Gemini] Function calls:")
    for call in calls:
        print(f"- name: {call.name}, arguments: {dict(call.args) if hasattr(call, 'args') else call.args}")


def run_openai(history: List[Dict[str, str]], user_prompt: str, model: str, tools: List[Dict[str, Any]]) -> None:
    if openai is None:
        print("openai package is not installed. Please pip install openai.", file=sys.stderr)
        return
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return
    messages = openai_messages(history, user_prompt)
    print(f"[OpenAI] Sending {len(messages)} messages with {len(tools)} tools.")

    if hasattr(openai, "OpenAI"):  # modern SDK
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
    else:  # legacy SDK
        openai.api_key = api_key
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
    print_tool_attempts_openai(response)


def run_gemini(history: List[Dict[str, str]], user_prompt: str, model: str, tools: List[Dict[str, Any]]) -> None:
    if genai is None:
        print("google-generativeai package is not installed. Please pip install google-generativeai.", file=sys.stderr)
        return
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.", file=sys.stderr)
        return
    genai.configure(api_key=api_key)
    messages = gemini_messages(history, user_prompt)
    declarations = gemini_function_declarations(tools)
    print(f"[Gemini] Sending {len(messages)} messages with {len(declarations)} function declarations.")
    model_client = genai.GenerativeModel(model_name=model, tools=[{"function_declarations": declarations}])
    response = model_client.generate_content(messages)
    print_tool_attempts_gemini(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dual provider function-calling demo.")
    parser.add_argument("--provider", choices=["openai", "gemini"], default="openai", help="Model provider to use.")
    parser.add_argument("--history-file", default=HISTORY_PATH_DEFAULT, help="Path to conversation history JSON.")
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip loading conversation history and only send the new user prompt.",
    )
    parser.add_argument("--env-file", default=ENV_PATH_DEFAULT, help="Optional .env file to load.")
    parser.add_argument(
        "--openai-model",
        default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        help="OpenAI model name.",
    )
    parser.add_argument(
        "--gemini-model",
        default=os.getenv("GEMINI_MODEL", "gemini-2.5-pro"),
        help="Gemini model name.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env_file)
    history = [] if args.no_history else load_history(args.history_file)

    tools = tool_definitions()
    user_prompt = build_user_prompt()

    if args.provider == "openai":
        run_openai(history, user_prompt, args.openai_model, tools)
    else:
        run_gemini(history, user_prompt, args.gemini_model, tools)


if __name__ == "__main__":
    main()
