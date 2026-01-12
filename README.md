# PrefIx: Preference-Aware Interactive Evaluation of LLM Agents

PrefIx is an interactive evaluation environment that simulates users with diverse interaction preferences and evaluates both task correctness and interaction quality. It is built to study how agents align to user preferences in multi-turn tool-use settings.

PrefIx is developed around four principles:

- Task coarsening: rewrite overly-specified prompts into coarser task instructions while preserving deterministic tool-use ground truth.
- Preference-aware user simulation: 31 preference settings across 14 attributes and 4 dimensions, expressed implicitly by the simulator.
- Interaction as a Tool (IaaT): represent interaction behaviors as structured tool calls to enable measurable alignment.
- UX judge: evaluate interaction quality across multiple dimensions, including interaction preference alignment.

This repo contains the full PrefIx pipeline and results for four test models:
- `claude-opus-4.5`
- `claude-sonnet-4.5`
- `gemini-3-flash`
- `kimi-k2`

The same four models are used as LLM-as-judge, and tool-use correctness checks are also run.

## Environment

Conda environment name: `ix_personalization`

The requirements exported from that environment are here:
- `<PROJECT_ROOT>/requirements.txt`

Setup:

```bash
conda create -n ix_personalization python=3.10
conda activate ix_personalization
pip install -r <PROJECT_ROOT>/requirements.txt
```

API keys live in:
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/.env`

## Code structure

Most code lives in:
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard`

Where to check supported model names:
- Canonical mapping: `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval/constants/model_config.py`
- Human-readable list: `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/SUPPORTED_MODELS.md`

Key locations:
- `<PROJECT_ROOT>/Processing`: rewritten task instructions (coarsened prompts).
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval`: core PrefIx pipeline.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval/LLM_as_judge_analysis`: analysis notebooks and CSVs for judge-based UX metrics, including multi-model comparisons and per-dimension breakdowns.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval/user_simulator`: simulator + prompts.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval/model_handler`: handlers + gating mechanisms.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/LLM_as_judge_score_repro`: reproducibility artifacts for LLM-as-judge.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/LLM_as_judge_score`: layout is `judge_model / test_model / setting / preference / sample`.
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/scores_persona`: tool-use accuracy for personalization vs no_personalization.

## How to run

All commands assume:

```bash
cd <PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard
```

### Working directory and required env vars

```bash
cd <PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard
export BFCL_PROJECT_ROOT="$(pwd)"
export PYTHONPATH="$BFCL_PROJECT_ROOT"
mkdir -p logs
export OPENROUTER_API_KEY=...        # required
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"  # optional
```

Progress tail (replace log name as needed):

```bash
tail -f logs/persona_matrix_gemini_3_flash.log
```



Progress check (Check the progress runing status based on the output files, replace <model> with the model being used. Progress check summarizes persona coverage and completion status. It reports completed runs, missing logs, and incomplete runs (e.g., logs without `<END_SIMULATION>`), so you can decide whether to clean or re-run specific subsets.):

```bash
python scripts/check_persona_progress.py --model claude-opus-4-5-20251101-FC
```



### History cleanup options

```bash
python scripts/clean_history_logs.py
python scripts/clean_history_logs.py --model claude-opus-4-5-20251101-FC --variant personalization
python scripts/clean_history_logs.py --model claude-opus-4-5-20251101-FC --personas each_confirmation,silent
python scripts/clean_history_logs.py --model claude-opus-4-5-20251101-FC --variant personalization --delete-incomplete
python scripts/clean_history_logs.py --model claude-opus-4-5-20251101-FC --variant personalization --personas each_confirmation,silent --delete-incomplete
```

History cleanup removes or truncates stale/partial simulator histories and optionally deletes incomplete runs. This prevents old or broken histories from contaminating fresh evaluations, especially after interrupted runs or prompt changes.

### Copy history from template
This step is required before running any new models. It initializes the first few lines of the history to reflect the specific interaction preferences, including an initial error and model setup.

```bash
python scripts/bootstrap_history_from_template.py --model kimi-k2-0905-preview-FC
```

### Deterministic checker
The deterministic checker (`bfcl_eval/scripts/deterministic_checker.sh`) verifies that model outputs are consistent and repeatable for the same input across runs. It reruns the persona evaluations and flags any differences in results, helping ensure leaderboard reliability and reproducibility. If a model produces varying outputs for the same input, it will be flagged as non-deterministic and may be disqualified.
Run this script after generating model outputs to verify their function calling performance (change <model> in the bash file to run for specific models). 
```bash
bash bfcl_eval/scripts/deterministic_checker.sh
```

### 1) Generate model outputs (4 test models)

```bash
python scripts/run_persona_matrix_claude_opus_4_5_20251101.py
python scripts/run_persona_matrix_claude_sonnet_4_5_20250929.py
python scripts/run_persona_matrix_gemini_3_flash.py
python scripts/run_persona_matrix_kimi.py
```

These scripts run all personas with and without interaction history. They require the rewritten tasks in `<PROJECT_ROOT>/Processing`.

### 2) Correctness check (tool-use accuracy)

```bash
python -m bfcl_eval evaluate --model claude-opus-4-5-20251101-FC --test-category multi_turn_long_context
python -m bfcl_eval evaluate --model claude-sonnet-4-5-20250929-FC --test-category multi_turn_long_context
python -m bfcl_eval evaluate --model gemini-3-flash-FC --test-category multi_turn_long_context
python -m bfcl_eval evaluate --model kimi-k2-0905-preview-FC --test-category multi_turn_long_context
```

Aggregates are stored in:
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/scores_persona`

### 3) LLM-as-judge (UX metrics)

Judge runner:
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/bfcl_eval/eval_checker/LLM_as_a_judge/run_gemini_judge.py`

Example (run one judge model):

```bash
python bfcl_eval/eval_checker/LLM_as_a_judge/run_gemini_judge.py \
  --judge-model claude-opus-4.5 \
  --personalization all
```

Outputs are stored under:
- `<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/LLM_as_judge_score/<judge_model>/...`


## Per-Model Runbook
All models can be run using the same steps, just replacing the relevant `--model` value and script name as appropriate.
Below is a complete workflow example for `claude-opus-4-5-20251101-FC`:

1. (Mandatory) Initialize history:

```bash
python scripts/bootstrap_history_from_template.py --model claude-opus-4-5-20251101-FC
```

2. Start main persona run script (recommended to use `nohup` and log/pid files):

```bash
nohup <PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python scripts/run_persona_matrix_claude_opus_4_5_20251101.py \
  > logs/persona_matrix_claude_opus_4_5_20251101.log 2>&1 & echo $! > logs/persona_matrix_claude_opus_4_5_20251101.pid
```

3. Check progress:

```bash
python scripts/check_persona_progress.py --model claude-opus-4-5-20251101-FC
```

4. Clean up incomplete/failed runs to prepare for re-run:

```bash
python scripts/cleanup_persona_runs.py --model claude-opus-4-5-20251101-FC
```

5. Delete error runs:

```bash
<PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python \
  "<PROJECT_ROOT>/scripts/cleanup_missing_end.py" \
  --model claude-opus-4-5-20251101-FC \
  --status-file "<PROJECT_ROOT>/gorilla/berkeley-function-call-leaderboard/scripts/file_status_claude-opus-4-5-20251101-FC.txt"
```

6. LLM-as-judge evaluation (repeat for each judge model):

    Available judge models:
    - anthropic/claude-opus-4.5
    - anthropic/claude-sonnet-4.5
    - google/gemini-3-flash-preview
    - moonshotai/kimi-k2-0905

```bash
nohup <PROJECT_ROOT>/.conda/envs/ix_personalization/bin/python bfcl_eval/eval_checker/LLM_as_a_judge/run_gemini_judge.py \
  --model claude_opus_4_5_20251101_FC \
  --personalization all \
  --judge-model anthropic/claude-opus-4.5 \
  --skip-existing \
  > logs/run_judge_anthropic_claude_opus_4_5_model_opus_4_5_20251101_FC.log 2>&1 & echo $!
```
