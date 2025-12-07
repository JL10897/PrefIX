# Repository Guidelines

## Project Structure & Module Organization
- `gorilla/` hosts the core inference pipeline (`inference/`) and evaluation utilities.
- `berkeley-function-call-leaderboard/` packages the BFCL evaluator; datasets sit in `bfcl_eval/data/` beside schema-check scripts.
- `agent-arena/client/` is the React dashboard with co-located assets and component tests.
- `goex/` provides the execution engine with reversible functions in `function/` and Docker fixtures under `docker/`.
- `raft/` contains domain RAG pipelines, configuration helpers, and `tests/`; shared datasets and API specs live in `data/` and `openfunctions/`.

## Build, Test, and Development Commands
- Python env: `python -m venv .venv && source .venv/bin/activate` then `pip install -r gorilla/gorilla/requirements.txt`.
- BFCL tooling: `cd berkeley-function-call-leaderboard && pip install -e .` to expose the `bfcl` CLI.
- GoEx CLI: `cd goex && pip install -e .` before running `python cli.py` or the demo workflows.
- Agent Arena UI: `cd agent-arena/client && npm install && npm start`; use `npm run build` before publishing assets.

## Coding Style & Naming Conventions
- Use Python 3.10+, four-space indentation, `snake_case` functions, and `PascalCase` classes; add type hints and docstrings for public APIs.
- Keep configuration in YAML or `.env` files instead of literals; reuse helpers like `env_config.py` when wiring services.
- For React files, follow the `react-app` ESLint defaults, prefer `PascalCase.jsx` for components, and keep hooks/utilities in `camelCase.js` modules.

## Testing Guidelines
- Python suites live under `tests/`; run `pytest` from directories such as `raft/` after installing dev requirements.
- Agent Arena uses Jest via `npm test`; co-locate specs as `<Component>.test.js` beside the component being exercised.
- For BFCL dataset changes, run `cd berkeley-function-call-leaderboard/bfcl_eval/scripts && python check_func_doc_format.py` to validate schema and enums.

## Commit & Pull Request Guidelines
- Use imperative, ≤72 character subjects with optional scope tags (e.g., `agent-arena: tighten ranking filter`) and expand details in wrapped body paragraphs.
- Reference issues with `Closes #123`, attach CLI logs or screenshots for UI and evaluation output, and note any new env vars or credentials.
- PR descriptions should list touched subdirectories, summarize verification steps, and mention follow-up tasks if coverage is deferred.

## Security & Configuration Tips
- Never commit secrets; copy `.env.example` files (e.g., `bfcl_eval/.env.example`) into local `.env` files and document required keys in the PR.
- Review reversible action scripts in `goex/function/` when adding new tools, and smoke-test with the provided Docker fixtures before requesting review.

## BFCL_eval 文件结构说明
- `bfcl_eval/__init__.py`：暴露包级导入，协调 CLI 与内部模块。
- `bfcl_eval/__main__.py`：`bfcl` 命令入口，负责解析参数并触发评测。
- `bfcl_eval/_llm_response_generation.py`：统一 LLM 请求/响应的生成与解析逻辑。
- `bfcl_eval/utils.py`：提供类别解析、JSON 读写与序列化等通用工具。
- `bfcl_eval/.env.example`：列出运行评测所需的环境变量模板。
- `bfcl_eval/test_case_ids_to_generate.json.example`：示例性用例 ID 清单，指导生成增量题目。

### constants 模块
- `constants/__init__.py`：整理常量命名空间。
- `model_config.py`：各模型的默认超参与端点配置。
- `supported_models.py`：受支持模型与标签清单。
- `eval_config.py`：评测运行时的阈值、路径与选项。
- `default_prompts.py`：多种提示词模板。
- `column_headers.py`：统计报表的列名定义。
- `type_mappings.py`：参数类型转换映射，辅助 schema 校验。
- `category_mapping.py`：测试集合与 JSON 文件的映射关系。

### model_handler 顶层
- `model_handler/__init__.py`：汇总 handler。
- `base_handler.py`：抽象基类，统一签名和轮询逻辑。
- `model_style.py`：区分 completion、response、工具调用等模式。
- `utils.py`：通用的限流、重试与格式化函数。

### model_handler/local_inference
- `base_oss_handler.py`：本地/开源模型 handler 的公共逻辑。
- `arch.py`：面向 ARCH 系列模型的调用封装。
- `bielik.py`：Bielik 模型评测适配。
- `bitagent.py`：BitAgent 推理入口。
- `deepseek.py`、`deepseek_coder.py`、`deepseek_reasoning.py`：DeepSeek 不同变体的本地推理。
- `falcon_fc.py`：Falcon 函数调用专用 handler。
- `gemma.py`：Gemma 模型封装。
- `glm.py`：GLM 系列模型封装。
- `granite.py`、`granite_3.py`：Granite 系列 handler。
- `glaive.py`：Glaive 模型。
- `hammer.py`：Hammer 模型。
- `hermes.py`：Hermes 模型。
- `llama.py`、`llama_3_1.py`：Llama 不同版本。
- `mistral_fc.py`：Mistral 函数调用版本。
- `minicpm.py`、`minicpm_fc.py`：MiniCPM 及函数调用变体。
- `phi.py`、`phi_fc.py`：Phi 系列及函数调用。
- `qwen.py`、`qwen_fc.py`：Qwen 通用与函数调用封装。
- `salesforce_llama.py`、`salesforce_qwen.py`：Salesforce 发布的变体支持。
- `think_agent.py`：Think Agent 推理。
- `quick_testing_oss.py`：轻量脚本，用于快速验证本地模型输出。

### model_handler/api_inference
- `__init__.py`：导出可用 API handler。
- `gorilla.py`：调用 Gorilla 自建推理服务。
- `nvidia.py`：对接 NVIDIA Inference Microservice。
- `mistral.py`：Mistral 平台接口封装。
- `mining.py`：对接 Mining Company API（内部评测）。
- `claude.py`：Anthropic Claude 工具调用封装。
- `openai_completion.py`：旧版 OpenAI Completion API。
- `novita.py`：Novita Cloud 模型接口。
- `grok.py`：xAI Grok API。
- `gemini.py`：Google Gemini Response API。
- `nemotron.py`：Nemo/Nemotron API。
- `ling.py`：Ling API 封装。
- `openai_response.py`：OpenAI Responses API 主实现。
- `openai_response_backup.py`：OpenAI Responses API 备份实现。
- `nexus.py`：NexusFlow/NexusRaven 接口。
- `fireworks.py`：Fireworks AI API。
- `qwen.py`：阿里云通义千问云端接口。
- `deepseek.py`：DeepSeek 官方 API。
- `yi.py`：零一万物 Yi API。
- `gogoagent.py`：GogoAgent 评测接口。
- `functionary.py`：Functionary API。
- `writer.py`：Writer SDK 封装。
- `databricks.py`：Databricks Foundation/DBRX API。
- `cohere.py`：Cohere Command 系列。
- `nova.py`：AWS Nova 模型。
- `dm_cito.py`：DeepMind CITO/输出 API。

### model_handler/parser
- `java_parser.py`、`js_parser.py`：将模型输出的 Java/JS 代码解析为可执行结构。
- `__init__.py`：导出解析器。

### eval_checker
- `eval_checker/__init__.py`：聚合导出。
- `eval_runner.py`：按配置加载数据集、模型 handler 并执行评测。
- `eval_runner_helper.py`：运行期辅助函数（打分、指标聚合）。
- `ast_eval/ast_checker.py`：通过抽象语法树检查函数调用合法性。
- `multi_turn_eval/multi_turn_checker.py` 与 `multi_turn_utils.py`：多轮对话特定的状态跟踪与判分。

### scripts
- `_compile_helper.py`：多轮函数描述的生成辅助。
- `compile_multi_turn_func_doc.py`：汇总/编译多轮函数文档。
- `check_func_doc_format.py`：校验函数描述 JSON 的字段合法性。
- `check_illegal_python_param_name.py`：检测保留关键字等非法参数名。
- `visualize_multi_turn_ground_truth_conversation.py`：输出多轮基准的可视化文本。

### data 根目录
- `README.md`：解释各个数据集的使用方式。
- `BFCL_v3_simple.json`：单轮、单函数的基础集。
- `BFCL_v3_irrelevance.json`：干扰/无关请求测试。
- `BFCL_v3_parallel.json`、`BFCL_v3_parallel_multiple.json`：并行调用能力测试。
- `BFCL_v3_multiple.json`：串行多调用场景。
- `BFCL_v3_java.json`、`BFCL_v3_javascript.json`：语言特定的代码生成用例。
- `BFCL_v3_live_simple.json`、`BFCL_v3_live_multiple.json`、`BFCL_v3_live_parallel.json`、`BFCL_v3_live_parallel_multiple.json`、`BFCL_v3_live_irrelevance.json`、`BFCL_v3_live_relevance.json`：实时接入第三方 API 的评测集合。
- `BFCL_v3_multi_turn_base.json`、`BFCL_v3_multi_turn_long_context.json`、`BFCL_v3_multi_turn_miss_func.json`、`BFCL_v3_multi_turn_miss_param.json`：多轮对话基准，覆盖长上下文与缺参/缺函数场景。
- `BFCL_v3_live_parallel_multiple.json` 等文件名称即表示测试形态，可按需要扩展。

### data/multi_turn_func_doc
- `gorilla_file_system.json`、`math_api.json`、`message_api.json`、`posting_api.json`、`ticket_api.json`、`trading_bot.json`、`travel_booking.json`、`vehicle_control.json`：分别提供各多轮场景中的函数描述、参数 schema 与背景。

### data/possible_answer
- 与主数据集同名的 JSON（`BFCL_v3_simple.json` 等）存放参考答案，便于判分；每个文件一行一条黄金响应。

### data/unused_datasets
- `question/*.json`：早期未纳入 V3 的题面备份（exec、rest、sql、chatable 等）。
- `possible_answer/*.json`：对应题面的黄金答案。
- `executable_eval_sanity_check/api_status_check_ground_truth_*.json`：REST/Executable 回归测试的期望调用结果。

### 其他说明
- `data/multi_turn_func_doc` 与 `possible_answer` 子目录下的 JSON 名称均表征具体场景；内容为嵌套结构，适合通过 `jq` 或 Python 读取。
- 各目录中的 `__pycache__` 文件夹仅用于 Python 字节码缓存，可忽略。

## Repository 阅读顺序建议
- **全局规则先行**：从 `AGENTS.md`（本文件）和仓库根部的 `gorilla/README.md` 入手，掌握统一的命名、测试与安全要求；随后通过 `Data_Explore.ipynb` 与 `gorilla/Dataset.ipynb` 快速浏览数据分布，再结合 `gorilla/data/` 与 `gorilla/openfunctions/` 观察 schema，建立函数描述与题目之间的映射。
- **聚焦 BFCL 主仓**：进入 `gorilla/berkeley-function-call-leaderboard/README.md`，按照其中的安装步骤创建环境、执行 `pip install -e .`、设置 `BFCL_PROJECT_ROOT`，并在项目根复制 `.env.example` 及 `test_case_ids_to_generate.json.example`，以便 `bfcl generate` / `bfcl evaluate` 找到配置与结果目录（`result/`、`score/`）。
- **顺藤摸瓜读代码**：依据 README 描述的 CLI 流程，自上而下阅读 `bfcl_eval/__main__.py`、`openfunctions_evaluation.py`、`eval_checker/`、`model_handler/`（`api_inference` 与 `local_inference`）和 `constants/`，同时结合 `SUPPORTED_MODELS.md`、`TEST_CATEGORIES.md`、`LOG_GUIDE.md` 理解各 flag、生成功能与日志输出之间的关系。
- **理解数据与执行链路**：在掌握 CLI 后，深入 `bfcl_eval/data/`、`data/multi_turn_func_doc/`、`data/possible_answer/`，对应 README 中的测试分类与 `--run-ids` 场景，再结合 `gorilla/goex/` 的可逆函数与 Docker fixture、`gorilla/gorilla/` 的推理工具链，明白模型 handler 如何触发真实函数调用。
- **扩展与可视化**：当需要自定义 handler 或可视化结果时，参考 `bfcl_eval/model_handler/base_handler.py` 和 `constants/model_config.py` 进行扩展；完成评测后可将 `score/*.csv`、`result/*` 丢给 `gorilla/agent-arena/` 前端查看，用 README 的日志说明辅助定位问题。
- **验证与后续工作**：结合 `raft/tests/` 里的 `pytest` 模式复用评测思路，必要时依 README 中的 `python -m bfcl_eval.*` 脚本方式复现 CLI；若要记录 WandB，记得安装 `.[wandb]` 并在 `.env` 写入 `WANDB_BFCL_PROJECT`。

## Iterative 文件结构导览
1. **根目录 `/`**：`AGENTS.md`（当前指南）、`README.md`、`Data_Explore.ipynb`，先读统一规则与数据概览。
2. **`gorilla/`**：仓库主干，包含：
   - `berkeley-function-call-leaderboard/`：BFCL 代码与 README，重点关注 `bfcl_eval/`、`data/`、`result/`、`score/`。
   - `agent-arena/`：前端可视化，子目录 `client/` 处理 React UI 与测试。
   - `goex/`：函数执行引擎，`function/` 定义可逆操作，`docker/` 提供测试容器。
   - `gorilla/`（同名包）：通用推理/工具库，供 handler 复用。
   - `data/`：`api/` 核心 API 描述、`apibench/` 基准集、`apizoo/` 社区贡献库。
   - `openfunctions/`：OpenFunctions 模型脚本（`inference_hosted.py`、`inference_local.py`）、解析工具 `openfunctions_utils.py` 和 `utils/`。
   - `raft/`：RAG 流水线与 `tests/`。
3. **支持性文件**：`Dataset.ipynb`（数据探索）、顶层 `LICENSE`（Apache 2.0），按需查阅。

• - gorilla/data/ 承载 Gorilla API Store（gorilla/data/README.md:1-147），内含 apibench 与 apizoo。apibench 提供按 API
    划分的 *_train.jsonl/*_eval.jsonl 数据集，用来在评测和训练时验证模型能否根据 API 说明构造请求；apizoo、api/ 等子目
    录收集社区提交的 API JSON 或 URL JSON（README 中给出字段定义和示例），为 BFCL、OpenFunctions 等场景提供高质量的函数
    描述、参数 schema 与真实问答。换言之，当你需要扩展测试集、校验模型对不同 API 的泛化时，就会读这里的文档、JSON 并按
    README 的格式贡献或引用数据。
  - gorilla/openfunctions/ 则是 OpenFunctions 模型与工具链的落地目录（gorilla/openfunctions/README.md:1-200）。它提供
    v0/v1/v2 模型的使用说明、Prompt/Response 规范、OpenAI 函数接口兼容示例、inference_hosted.py 和 inference_local.py
    等脚本，以及 openfunctions_utils.py、openfunctions-v1/、utils/ 中的解析函数。BFCL 在 SUPPORTED_MODELS.md 中列出的
    gorilla-openfunctions-* 系列就是依赖这里发布的模型；当你需要本地/托管推理、解析函数调用字符串、或理解多函数/并行调
    用/多语言类型支持时，就会回到此目录。
    


  1. 根目录 /
      - AGENTS.md：工作流/命名/安全/测试规范（需先读）。
      - README.md：仓库总览，链接到子项目。
      - Data_Explore.ipynb：高层数据探索。
      - gorilla/：所有子仓都在这里。
  2. gorilla/ 子目录
      - berkeley-function-call-leaderboard/
          - README.md：BFCL 安装、CLI、BFCL_PROJECT_ROOT 配置。
          - bfcl_eval/
              - __main__.py → CLI 入口 bfcl.
              - openfunctions_evaluation.py、eval_checker/：生成与打分核心。
              - model_handler/（api_inference/, local_inference/, parser/）实现不同模型的 handler。
              - constants/：model_config.py、default_prompts.py、category_mapping.py 等常量。
              - utils.py、_llm_response_generation.py：通用工具。
          - data/：BFCL_v3_*.json 题面，multi_turn_func_doc/ 函数说明，possible_answer/ 标准答案。
          - result/、score/：运行 CLI 后生成的输出（可按模型/类别查 JSON、CSV）。
          - scripts/：check_func_doc_format.py 等校验/可视化脚本。
      - agent-arena/
          - client/：React app，含 src/、public/、__tests__/。
          - package.json、npm scripts：npm install/npm start。
      - goex/
          - function/：可逆函数定义。
          - docker/：执行环境镜像。
          - cli.py：交互入口（需 pip install -e .）。
      - gorilla/（包）
          - inference/、evaluation/ 等工具模块（供 handler 或其他项目引用）。
          - requirements.txt：Python 依赖。
      - data/
          - api/：huggingface_api.jsonl、torchhub_api.jsonl、tensorflowhub_api.jsonl。
          - apibench/：{api}_train.jsonl / {api}_eval.jsonl。
          - apizoo/：用户贡献的 API JSON 或 URL JSON。
          - README.md：贡献指南。
      - openfunctions/
          - README.md：OpenFunctions v2 介绍。
          - inference_hosted.py、inference_local.py：托管/本地调用示例。
          - openfunctions_utils.py → 依赖 utils/python_parser.py、java_parser.py、js_parser.py。
          - openfunctions-v1/：v1 训练/测试数据与 README。
          - requirements.txt：OpenFunctions 运行依赖。
      - raft/
          - config/、pipelines/、tests/：领域 RAG 配置与 pytest 用例。
          - data/, openfunctions/：共享资源与 API 规格。
  3. 其他支持文件
      - Dataset.ipynb（位于 gorilla/）补充数据分析。
      - 根目录 LICENSE（Apache 2.0）。
      - 任何 .env.example → 复制到项目根配置 API Keys。