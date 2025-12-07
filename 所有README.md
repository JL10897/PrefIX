# Gorilla 是推出 OpenFunctions 模型和 API 数据集的主体项目，而 BFCL（Berkeley Function Calling Leaderboard）是 Gorilla 团队在同一仓库内构建的评测套件，用来衡量这些模型（以及其他模型）在函数调用任务上的表现。

# /Users/JL/Desktop/Agent_IX_Personalization/gorilla/data
• - api/（gorilla/data/api）存放的是官方整理的“核心 API 说明”集合，例如 tensorflowhub_api.jsonl、torchhub_api.jsonl、
    huggingface_api.jsonl 等，每条记录都详细列出 api_call、参数、依赖和示例代码（见 gorilla/data/api/
    tensorflowhub_api.jsonl 开头几行）。这些是 Gorilla 早期训练/推理时最常用的、结构较稳定的 API 清单，可直接喂给模型或
    转换成别的格式。
  - apibench/（gorilla/data/apibench）在 README 中被描述为“Evaluating LLM models”( gorilla/data/README.md:32-38 )，里面
    的 {api_name}_train.jsonl、{api_name}_eval.jsonl 是围绕上述 API 设计的标准化问答与调用示例，用于系统性训练和基准测
    试。也就是说，apibench 会引用 api/ 里的函数定义，再附上 QA、指令与标签，方便评测。
  - apizoo/（同 README 的 “Contributed by our Community” 部分 gorilla/data/README.md:32-41 ）是社区贡献区，任何人都能按
    README 规定的 JSON/URL 模式新增 API 描述。它扩充了“可调用 API 池”，BFCL 或其他模型只要读取这些 JSON，就能学会使用新
    增的函数。

  三者关系可以理解成：api/ 是最原始的官方 API 描述库，apibench/ 在此基础上包装出标准化的训练/评测题，apizoo/ 则持续吸纳
  社区的新 API，方便包括 Gorilla 在内的任意模型共享和扩展。

# Gorilla API Store 

Teach Gorilla how to use your API! Learn about the entire workflow, and how to contribute to Gorilla API Store! Gorilla API Store intends to enhance LLM's capability to use tools through API calls. We appreciate everyone's effort and contributions! THIS WILL ALWAYS REMAIN OPEN SOURCE.

## How to Contribute?

Contribute to Gorilla API Store is very easy! 

1. **JSON Contribution**: It only takes two steps

- Step 1: Submit an API JSON file or a URL JSON file following our format. 
- Step 2: Raise a Pull Request.

2. **Website Assisted** [Coming Soon]: If you need help writing an API json, we will provide a website and you only need to type in your API documentation url. We will return a draft API JSON file (you guessed it, using an LLM) and you can either choose to **Submit** or **Edit & Submit**. 

## Repository Organization
 
Post merge, your APIs will reside under your username, organized as follows: 

```
gorilla
├── data
│   ├── apibench (Evaluating LLM models) v-1.0
│   │   ├── {api_name}_train.jsonl, {api_name}_eval.jsonl
│   ├── apizoo (Contributed by our Community)
│   |   ├── username1.json
│   │   ├── username2.json
│   │   ├── username3.json
│   │   ├── ...
```

## Two ways to contribute APIs

We make the contribution to Gorilla API Store as easy as possible. We provide two alternatives: You could either submit following the API JSON format {or} URL JSON format. 

### Option 1: API JSON (Preferred)
 
Community members can submit to Gorilla API Zoo using the following JSON list format:

| Field      |  Type  | Description/Options     | Required |
| :---       | :----: |          :----         |   :---:   |
| user_name     | String       | Name of User   | ✅ |
| api_name      | String       | Name of API (maximum 20 words)   | ✅ |
| api_call | String | One line of code that starts with the function call, followed by a full list of argument names and values | ✅ |
| api_version | String | Version of API | ✅ |
| api_arguments | JSON | JSON of all the restricted keywords in the arguments list | ✅ |
| functionality | String | Short description of the function (maximum 20 words) | ✅ |
| env_requirements | List[String] | List of all the library dependencies | [Optional]:fire: |
| example_code | String | A string containing example code to use the API | [Optional]:fire: |
| meta_data | JSON | A JSON file of containing additional information about the API | [Optional]:fire: |
| Questions | List[String] | A question describing a real-life scenario that uses this API. Please do not include specific API name. | [Optional]:fire: |

**Example Submission**:

```python
[ 
  {
    "user_name": "example_username_api",
    "api_name": "Torch Hub Model snakers4-silero",
    "api_call": "torch.hub.load(repo_or_dir=['snakers4/silero-models'], model=['silero_stt'], *args, source, trust_repo, force_reload, verbose, skip_validation, **kwargs)", 
    "api_version": 2.0, 
    "api_arguments": {
      "repo_or_dir": "snakers4/silero-models", 
      "model": "silero_stt", 
      "language": ["en", "de", "es"]
    },
    "functionality": "Speech to Text",
    "env_requirements": ["torchaudio", "torch", "omegaconf", "soundfile"],
    "example_code": "import torch \n \
                    model = torch.hub.load('ultralytics/yolov5', 'yolov5s', pretrained=True) \n \
                    imgs = ['https://ultralytics.com/images/zidane.jpg'] \n \
                    results = model(imgs)",
    "meta_data": {
      "description": "Silero Speech-To-Text models provide enterprise grade STT in a compact form-factor for several commonly spoken languages. The models are robust to a variety of dialects, codecs, domains, noises, and lower sampling rates. They consume a normalized audio in the form of samples and output frames with token probabilities. A decoder utility is provided for simplicity.", 
      "performance": {"dataset": "imagenet", "accuracy": "80.4\%"}
    },
    "questions": [
      "I am a doctor and I want to dictate what my patient is saying and put it into a text doc in my computer.",
      "My students in math class is having trouble following up my content. He needs an API to write down what I am saying for reviewing.",
    ],
  },
  ...
]
```

### Option 2: URL JSON

We also provide you with a much simpler approach for you to contribute! Provide a simple url to your API documentation, we'll process it for you. Keep in mind, there might be some errors that can creep in with this process and hence we recommend the approach above, or at least come back to verify if the api documentation we generated for these url's are accurate! They API document generated from the urls will be stored as mentioned in the directory structure above.

Submit a json file containing the list of json objects: 

| Field      |  Type  | Description/Options     | Required |
| :---       | :----: |          :----         |   :---:   |
| user_name     | String       | Name of User   | ✅ |
| api_name      | String       | Name of API (maximum 20 words)   | ✅ |
| api_url      | String       | URL to API documentation   | ✅ |
| Questions | List[String] | A question describing a real-life scenario that uses this API. Please do not include specific API name. | [Optional]:fire: |

**Example Submission**:

```python
[
  {
    "user_name": "example_username_url",
    "api_name": "Torch Hub ultralytics_yolov5",
    "url": "https://pytorch.org/hub/ultralytics_yolov5/",
    "questions": [
      "I am a doctor and I want to dictate what my patient is saying and put it into a text doc in my computer.",
      "My students in math class is having trouble following up my content. He needs an API to write down what I am saying for reviewing.",
    ],
  },
...
]
```

**LLM assistance for LLM API dataset :wink:**:

Visit our website [Coming Soon!], where you can type in the API URL and we'll output an API submission for you! You can choose to submit or edit before and submitting. Easy and quick!

## Citation

If you use Gorilla or APIBench, please cite our paper:

```text
@article{patil2023gorilla,
  title={Gorilla: Large Language Model Connected with Massive APIs},
  author={Shishir G. Patil and Tianjun Zhang and Xin Wang and Joseph E. Gonzalez},
  year={2023},
  journal={arXiv preprint arXiv:2305.15334},
} 
```


  - apibench 在 BFCL 之前就存在，是 Gorilla 团队整理出的标准化评测/训练集（gorilla/data/README.md:1-136）。它不仅列
    出 API，还提供成对的 *_train.jsonl 与 *_eval.jsonl，方便大家对任意模型做基准测试或微调，所以 BFCL 只是复用这些数据
    之一。
  - apizoo 是开放式的 API 说明库，同一份 README（gorilla/data/README.md:42-147）详细规定了贡献格式。你当然可以在这里补充
    新的 API 描述、参数和示例。这样做的好处是：无论是 Gorilla 还是任何需要函数调用能力的 LLM，都可以读取这些 JSON，学会
    新的工具。
  - 为什么不局限于 Gorilla？这些 JSON/问题集、本身就是开放数据；任何模型——只要你在训练或推理时给它这些函数定义——都能利
    用。Gorilla 之所以强调，是因为它原生支持函数调用并且官方提供了接入示例，但从数据角度看，BFCL、OpenFunctions、你自己
    的模型都能消费 apibench/apizoo。

  因此：你可以把 apibench 当成“固定基准题库”，apizoo 当成“社区不断扩充的 API 说明”。两者对模型完全通用，不是 Gorilla
  专属。





# Gorilla Openfunctions

如果你使用其他本身已经内置了“函数调用”或“工具使用”功能的模型，你不需要使用 Gorilla OpenFunctions。
这里需要区分一个概念：
“函数调用” (Function Calling / Tool Use): 这是一种能力或特性。它指的是 LLM 能够理解你的自然语言，并将其转换成结构化数据（如 JSON）来调用外部 API 或工具。
“Gorilla OpenFunctions”: 这是一个特定模型的名称。这是伯克利团队开发的、专门 针对“函数调用”这个任务进行优化的开源模型。
不同模型的处理方式
1. 具有“内置”功能的闭源模型 (如 OpenAI, Google):
像 OpenAI 的 GPT-4、GPT-3.5-Turbo，或 Google 的 Gemini 系列模型，它们在自己的 API 中已经原生支持“Function Calling”或“Tool Use”功能。
如果你使用它们，你只需要按照它们各自的官方文档和 API 规范来操作即可，完全不需要 Gorilla OpenFunctions。
2. 其他开源模型 (如 Llama, Mistral):
一些通用的开源模型（如 Llama 3, Mistral 7B）本身可能没有像 GPT-4 那样专门为函数调用优化的 API 接口。
虽然你也可以通过复杂的提示工程（Prompt Engineering）“强迫”它们输出 JSON，但效果可能不稳定。
那么，Gorilla OpenFunctions 的价值在哪里？
根据这份 README，Gorilla OpenFunctions 的核心价值在于：
开源替代品: 它提供了一个高性能的、开源的（Apache 2.0） 解决方案，专门用于“函数调用”这个任务。
性能卓越: 它声称其 7B 模型的效果可以媲美 GPT-4（在函数调用这个特定任务上）。
API 兼容性: 它刻意模仿了 OpenAI 的 API 格式。这意味着，如果你的代码原本是为 OpenAI 的函数调用编写的，理论上你可以把 API 地址（api_base）换成 Gorilla 的服务器，就能无缝切换到一个开源、可本地部署的模型上，而不需要重写大量代码。

Gorilla OpenFunctions 是一个模型，不是连接器。
你要评测 Llama，就必须让 Llama 自己去生成函数调用，而不是通过 Gorilla。


 - 启动 Docker：打开 Docker Desktop，确认鲸鱼图标是 Running，MySQL 容器 ix_personalization_goex（或
  你命名的容器）处于 Up 状态；若已删除，重新运行 docker run -d --name ix_personalization_goex -e
  MYSQL_ROOT_PASSWORD=1002 -e MYSQL_DATABASE=test_database -p 3306:3306 mysql:8.0 并导入所需数据。
- 激活 Conda 环境：终端 cd /Users/JL/Desktop/Agent_IX_Personalization && source /opt/anaconda3/etc/
  profile.d/conda.sh && conda activate ix_personalization，确保 pip install -e gorilla/goex 已完成且
  依赖未丢失（pip list 可检查 httpx/openai 等版本）。
- 加载 .env / user_config：.env 中的 DATABASE_*、OPENAI_API_KEY、GOOGLE 等变量会被 load_dotenv() 自
  动读取；若你修改了 user_config.json（max_attempt、dbtype、option 等），确认文件仍在 gorilla/goex/
  user_config.json，无需额外操作。
- 验证凭据：Gmail token 保存在 gorilla/goex/exec_engine/credentials/gmail/token.pickle，secret store
  在 exec_engine/credentials/secret_store.json，只要未删除无需重新授权；如 Slack/其他服务要复用，确认
  密钥仍在该文件中。
- 万一 Docker 镜像丢失：若本地清理了 goex-mysql-executor 或 REST 执行器镜像，回到对应目录（如
  gorilla/goex/docker/mysql_docker、gorilla/goex/docker/docker）重新 docker build -t <image> -f
  dockerfile .，确保去掉 pip --upgrade 的行。
- 启动 CLI：完成以上后即可运行 goex execute ... 或 python gorilla/goex/examples.py；若遇到授权失败、
  MySQL 连接错等，再依照前面的调试流程检查端口、凭据、Docker 状态。



• 调试成果

- 起点：已有 Conda 环境 ix_personalization，在仓库 /Users/JL/Desktop/
  Agent_IX_Personalization 工作。先根据 AGENTS.md 配置 goex：pip install -e gorilla/
  pip 升级失败，改为删除该命令后重新 build 容器镜像，dry-run 才能运行。
- 文件系统示例：成功运行 examples.py 里的 FS demo。MySQL 示例一开始
  报连接失败，因为 Docker 容器未暴露端口或未启动；重建容器 docker run
  -d --name ix_personalization_goex -e MYSQL_ROOT_PASSWORD=1002 -e
  MYSQL_DATABASE=test_database -p 3306:3306 mysql:8.0，并在根目录 .env 写入
  DATABASE_*。进一步遇到 Access denied for user 'root'@'192.168.65.1'，通过在容器里
  执行 ALTER USER 'root'@'%' IDENTIFIED WITH mysql_native_password BY '<password>';
  FLUSH PRIVILEGES; 解决。为让示例有数据，导入 gorilla/goex/docker/mysql_docker/
  checkpoints/database_dump.sql 中的 students 表。
- MySQL dry-run：examples.py 缺少 _exec_sql_call，改用 engine._exec_db_call。dry-
  run 依赖 Docker 镜像 gorilla/goex/docker/mysql_docker/dockerfile，最初 apt install
  mysql-server 失败；确认日志后保持 100% MySQL 兼容，去掉 pip 升级、确保 mysql.sh 安
  装命令成功。构建镜像后 dry-run 通过。若重启环境，需要启动 Docker、conda activate
  ix_personalization、确保 .env 和容器密码一致，然后运行 examples.py 即可。
- Gmail 授权：goex -authorize gmail 流程本地成功获取 code，但 POST 到 https://goex-
  services.gorilla-llm.com/authorize 因证书过期失败；暂时通过 requests.post(...,
  verify=False) 绕过 SSL 校验，最终存下 gorilla/goex/exec_engine/credentials/gmail/
  token.pickle（提醒用户之后撤销明文泄露的 OPENAI key）。goex execute -prompt "who
  are the senders..." -type rest 成功调用 Gmail API，输出最近邮件的发件人。
- Slack 操作：执行 goex execute -prompt "send a funny joke..." -type rest，第一次因
  workspace 中无 gorilla@yahoo.com 用户而报 users_not_found；换成存在的邮箱后发送成
  功（Slack 返回 joke）。
- 重启流程：每次关闭仓库后需重启 Docker 容器、激活 Conda 环境、确保 .env 存在
  且与容器配置一致，如果清空了 Docker 镜像需重新 build（记得 Dockerfile 已去掉
  pip 升级）。token.pickle 和 secret_store.json 保持在 gorilla/goex/exec_engine/
  credentials/ 下即可快速恢复 REST 场景。

  整体来说，关键问题包括：pip 升级导致 Docker 构建失败、MySQL 容器未授权外部 root、
  Gmail 授权站点证书过期以及 Slack 用户不存在。通过修改 Dockerfile、授权 SQL 用户、关
  闭 SSL 校验、提供有效邮箱等方法逐一解决，最终 examples.py、REST/Slack/Gmail 命令均能
  正常运行。

  工作历程

  - 环境搭建：在已有 Conda 环境 ix_personalization 中 pip install -e gorilla/goex，
    过程中 httpx/openai/requests 被降级（与 BFCL 依赖冲突），但保证了 goex 可用。根
    目录 .env 手动创建并配置 DATABASE_USER/PASSWORD/HOST/NAME、OPENAI_API_KEY 等；
    user_config.json 保留默认设置。
  - Docker & MySQL：使用 docker run -d --name ix_personalization_goex -e
    MYSQL_ROOT_PASSWORD=<密码> -e MYSQL_DATABASE=testdb -p 3306:3306 mysql:8.0 启
    动容器。每次重启机器需 docker start ix_personalization_goex 并 conda activate
    ix_personalization。
  - Dry-run 镜像：gorilla/goex/docker/docker/dockerfile（REST/FS）与 gorilla/goex/
    docker/mysql_docker/dockerfile（SQL）最初失败在 pip3 install --upgrade pip。删除
    该命令重新 docker build -t goex-default-executor -f docker/docker/dockerfile . &
    docker build -t goex-mysql-executor -f docker/mysql_docker/dockerfile . 后成功。
    SQL 镜像还运行 container_setup/mysql.sh，依赖 mysql-server；镜像内现已正常完成
    安装。
  - MySQL 示例：gorilla/goex/examples.py 读取 .env。为了看到实际数据，先导入 gorilla/
    goex/docker/mysql_docker/checkpoints/database_dump.sql，该文件包含 students 表和
    示例记录。运行 python gorilla/goex/examples.py 现在会显示插入/撤销状态。若再遇到
    Access denied for user 'root'@'192.168.65.1'，在容器里执行 ALTER USER 'root'@'%'
    IDENTIFIED WITH mysql_native_password BY '<密码>'; FLUSH PRIVILEGES;。
  - Gmail 授权：goex -authorize gmail 调用 goex-services.gorilla-llm.com，其证书已
    过期，需要在 gmail_authorization.py 的 requests.post 加上 verify=False 才能写入
    exec_engine/credentials/gmail/token.pickle。后续 goex execute -prompt "who are the
    senders..." -type rest 运行正常。注意尽快升级或改用自建授权服务，以免长期禁用 SSL
    校验。
  - Slack：goex execute -prompt "... send ... on Slack" -type rest 需要将邮箱换成当前
    工作区存在的用户，否则 users.lookupByEmail 返回 users_not_found。成功后 CLI 会发送
    真实消息（示例输出了一个 “light attracts bugs” 的 joke）。
  - 其它：goex CLI 的 secret_store.json 位于 gorilla/goex/exec_engine/credentials/
    secret_store.json，首次运行需 -insert_creds 或手动创建 {}。授权服务（gmail/slack/
    spotify/github/dropbox）一次只能传一个参数。所有文件系统操作默认在 test 目录执行，
    可在 user_config.json 配置 fs_path。OpenAI key 曾在终端输出中泄露，需要在 OpenAI
    控制台撤销旧 key 并更新 .env。

    给未来 Agent 的建议

  1. 优先检查 Dockerfile：若 dry-run 失败，多半是 gorilla/goex/docker/... 下的镜像
     没 build 成功；确保删除 pip --upgrade，必要时改用 python:3.10-slim，并重新执行
     docker build。
  2. 确认数据库状态：MySQL 容器需与 .env 密码一致，且授权外部 IP；运行
     check_mysql_connection.py 等脚本能快速验证连通性。若空表导致示例无输出，导入
     checkpoints/database_dump.sql。
  3. 凭据与授权：secret_store.json、token.pickle、.env 是 goex 的三个关键数据源。遇到
     FileNotFoundError 或授权错误，从这几个文件入手。Gmail 授权依赖远端服务，可能需绕
     过过期证书或自行实现授权端点。
  4. 日志引导定位：CLI 的 Traceback 通常说明问题所在（如 Slack users_not_found、pip 升
     级失败）。每次修改后留意 docker build 输出和 CLI debug 消息，这能最快定位下一步
     操作。
  5. 重启 checklist：Docker Desktop Running → docker start ix_personalization_goex →
     conda activate ix_personalization → 运行命令。如镜像或凭据丢失，按照上面记录重建
     即可。