"""
Helper entrypoint to debug persona CSV generation.
Usage (example):
  PYTHONPATH=. python bfcl_eval/scripts/run_persona_csv_debug.py \\
      --model-name claude-opus-4-5-20251101-FC \\
      --result-root result \\
      --output-root scores_persona
"""
import argparse
from pathlib import Path

from bfcl_eval.scripts.generate_multi_turn_persona_csv import (
    generate_persona_csvs_for_model,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-name",
        required=True,
        help="Model name directory under result/, e.g., claude-opus-4-5-20251101-FC",
    )
    parser.add_argument(
        "--result-root",
        default="result",
        help="Path to result root (default: result relative to repo root)",
    )
    parser.add_argument(
        "--output-root",
        default="scores_persona",
        help="Path to write CSV outputs (default: scores_persona relative to repo root)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    out = generate_persona_csvs_for_model(
        model_name=args.model_name,
        result_root=Path(args.result_root),
        output_root=Path(args.output_root),
    )
    print(f"✅ CSVs written to: {out}")


if __name__ == "__main__":
    main()
