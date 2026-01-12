"""
Convenience script to generate persona CSVs for Claude Opus 4.5 FC outputs.

Usage (from repo root):
  PYTHONPATH=. <PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python \
      bfcl_eval/scripts/run_persona_csv_claude.py
"""
from pathlib import Path

from bfcl_eval.scripts.generate_multi_turn_persona_csv import (
    generate_persona_csvs_for_model,
)


def main():
    out = generate_persona_csvs_for_model(
        model_name="gpt-5.1-2025-11-13-FC",
        result_root=Path("result"),
        output_root=Path("scores_persona"),
    )
    print(f"✅ CSVs written to: {out}")


if __name__ == "__main__":
    main()