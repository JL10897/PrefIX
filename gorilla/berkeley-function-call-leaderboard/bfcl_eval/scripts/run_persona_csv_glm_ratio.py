"""
Convenience script to generate persona coverage CSVs for Gemini FC outputs (ratio checker).

Usage (from repo root):
  PYTHONPATH=. <PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python \
      bfcl_eval/scripts/run_persona_csv_gemini_ratio.py
"""
from pathlib import Path

from bfcl_eval.scripts.generate_multi_turn_persona_csv_ratio import (
    generate_persona_csvs_for_model_ratio,
)


def main():
    out = generate_persona_csvs_for_model_ratio(
        model_name="glm-4.6",
        result_root=Path("result"),
        output_root=Path("scores_persona"),
    )
    print(f"✅ Coverage CSVs written to: {out}")


if __name__ == "__main__":
    main()
