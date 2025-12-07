#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compress the multi-turn user interaction to high-level task description。

功能特性：
1. 读取指定 JSONL 数据集（默认 multi_turn_long_context）。
2. 仅处理 [start_index, end_index) 范围内的记录，便于分批运行。
3. 使用 Gemini API（google-generativeai）将多轮对话合并为 JSON 指令。
4. 结果以 JSON 行的形式追加写入目标文件，绝不覆盖历史输出。
5. 运行参数（输入、输出、prompt 路径以及模型等）全可配置，方便后续复用到其他数据集。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, Iterable, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - 运行脚本前需安装依赖
    genai = None


# ----------------------------- 基础工具函数 ----------------------------- #
def load_prompt(template_path: Path) -> str:
    if not template_path.exists():
        raise FileNotFoundError(f"找不到提示词文件：{template_path}")
    return template_path.read_text(encoding="utf-8")


def iter_entries(
    dataset_path: Path, start_index: int, end_index: int | None
) -> Iterable[Tuple[int, Dict]]:
    """流式读取 JSONL，按索引过滤需要的记录。"""
    if not dataset_path.exists():
        raise FileNotFoundError(f"找不到数据文件：{dataset_path}")

    with dataset_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if idx < start_index:
                continue
            if end_index is not None and idx >= end_index:
                break
            if not line.strip():
                continue
            yield idx, json.loads(line)


def configure_gemini(api_key: str) -> None:
    """配置 Gemini API 客户端。"""
    if genai is None:
        raise RuntimeError("未安装 google-generativeai，请先 `pip install google-generativeai`。")
    if not api_key:
        raise RuntimeError("未提供 GEMINI_API_KEY，无法调用模型。")
    genai.configure(api_key=api_key)


def build_prompt(prompt_template: str, entry: Dict) -> str:
    """将单条样本插入模板中，返回最终 prompt。"""
    entry_json = json.dumps(entry, ensure_ascii=False)
    return prompt_template.replace("<INSERT USER TURNS HERE>", entry_json)


def _strip_code_fence(text: str) -> str:
    """如果模型外层包裹了 ```json ... ```，则剥离 fenced block。"""
    text = text.strip()
    if text.startswith("```"):
        # 处理 ```json ... ``` 或 ``` ...
        first_line_end = text.find("\n")
        if first_line_end != -1:
            fence = text[:first_line_end].strip("`")
            if fence.startswith("json") or fence == "":
                text = text[first_line_end + 1 :]
                if text.endswith("```"):
                    text = text[: -3]
    return text.strip()


def call_gemini(
    prompt: str,
    model_name: str,
    *,
    max_retries: int = 3,
    retry_delay: float = 5.0,
    default_wait: float = 30.0,
) -> Dict:
    """调用 Gemini 模型并返回解析后的 JSON 结果，内置轻量重试。"""
    model = genai.GenerativeModel(model_name)
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = model.generate_content(prompt)
            raw_text = response.text or ""
            cleaned = _strip_code_fence(raw_text)
            return json.loads(cleaned)
        except json.JSONDecodeError as err:
            raise ValueError(
                f"模型输出不是合法 JSON，原始文本：{raw_text}"
            ) from err
        except Exception as exc:
            last_error = exc
            sleep_time = default_wait
            message = str(exc)
            if "Please retry in" in message:
                try:
                    wait_part = message.split("Please retry in", 1)[1]
                    seconds = float(wait_part.split("s", 1)[0].strip())
                    sleep_time = max(seconds, retry_delay)
                except Exception:
                    sleep_time = default_wait
            elif isinstance(exc, (genai.types.generation_types.BlockedPromptException,)):
                raise

            if attempt < max_retries:
                print(f"[WARN] 调用失败（{exc}），等待 {sleep_time:.1f}s 后重试（{attempt}/{max_retries}）")
                time.sleep(sleep_time)
            else:
                break

    raise RuntimeError(f"调用 Gemini 多次失败：{last_error}")


def append_result(output_path: Path, record: Dict) -> None:
    """将单条结果以 JSON 行格式追加写入文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False)
        f.write("\n")


def load_status_map(status_path: Path) -> Dict[str, Dict]:
    """读取状态记录，返回 {id: {status, error}} 字典。"""
    if not status_path.exists():
        return {}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[WARN] 状态文件格式异常，忽略：{status_path}")
        return {}


def save_status_map(status_path: Path, status_map: Dict[str, Dict]) -> None:
    """覆盖写入最新状态映射。"""
    status_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = status_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(status_map, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(status_path)


# ----------------------------- 主流程 ----------------------------- #
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite BFCL"
    )
    default_input = Path(
        "/Users/JL/Desktop/Agent_IX_Personalization/gorilla/berkeley-function-call-leaderboard/bfcl_eval/data/BFCL_v3_multi_turn_long_context.json"
    )
    default_output = Path("/Users/JL/Desktop/Agent_IX_Personalization/Processing/BFCL_v3_multi_turn_long_context_rewrite.json")
    default_prompt = Path("/Users/JL/Desktop/Agent_IX_Personalization/Processing/Prompt_extractor.md")
    default_env = Path("gorilla/berkeley-function-call-leaderboard/.env")
    default_status = Path("Processing/rewrite_status.json")

    parser.add_argument(
        "--input-file",
        type=Path,
        default=default_input,
        help="Path to Original JSON dataset",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=default_output,
        help="Path to Rewrite output file",
    )
    parser.add_argument(
        "--prompt-file",
        type=Path,
        default=default_prompt,
        help="Path to Prompt",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default_env,
        help="Path to .env file (自动加载 GEMINI_API_KEY)",
    )
    parser.add_argument(
        "--status-file",
        type=Path,
        default=default_status,
        help="记录成功/失败状态的 JSON 文件",
    )
    parser.add_argument(
        "--model-name",
        default="gemini-2.0-flash-lite",
        help="Gemini Model）",
    )
    parser.add_argument(
        "--start-index",
        type=int,
        default=0,
        help="Start-indx (including)",
    )
    parser.add_argument(
        "--end-index",
        type=int,
        default=None,
        help="End-indx（not including）。为空则处理到文件末尾。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅打印将要处理的样本，不调用模型。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.env_file and args.env_file.exists():
        if load_dotenv is None:
            raise RuntimeError("检测到需要加载 .env，但未安装 python-dotenv，请先 `pip install python-dotenv`。")
        load_dotenv(args.env_file)
    elif args.env_file:
        print(f"[WARN] 指定的 .env 文件不存在：{args.env_file}")

    prompt_template = load_prompt(args.prompt_file)
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not args.dry_run:
        configure_gemini(api_key)

    status_map = load_status_map(args.status_file)
    total_processed = 0
    # 在 API 级别已经做了重试，这里可选在两次成功请求之间插入短暂 sleep
    request_interval = float(os.getenv("GEMINI_REQUEST_INTERVAL", "0"))

    for idx, entry in iter_entries(args.input_file, args.start_index, args.end_index):
        print(f"[INFO] 处理索引 {idx}，样本 ID={entry.get('id')}")
        entry_id = entry.get("id")
        status_record = status_map.get(entry_id)
        if status_record and status_record.get("status") == "success":
            print(f"[SKIP] {entry_id} 已成功处理，跳过。")
            continue

        prompt = build_prompt(prompt_template, entry)

        if args.dry_run:
            # print(prompt[:400] + ("..." if len(prompt) > 400 else ""))
            print(prompt)
            continue

        try:
            result = call_gemini(prompt, args.model_name)
        except Exception as exc:
            print(f"[ERROR] 样本 {entry.get('id')} 调用失败：{exc}")
            status_map[entry_id] = {"status": "failed", "error": str(exc)}
            save_status_map(args.status_file, status_map)
            continue

        # 确保 ID 没丢失
        result.setdefault("id", entry.get("id"))
        append_result(args.output_file, result)
        status_map[entry_id] = {"status": "success"}
        save_status_map(args.status_file, status_map)
        total_processed += 1
        if request_interval > 0:
            time.sleep(request_interval)

    print(f"[DONE] 本次追加写入 {total_processed} 条记录 -> {args.output_file}")


if __name__ == "__main__":
    main()
