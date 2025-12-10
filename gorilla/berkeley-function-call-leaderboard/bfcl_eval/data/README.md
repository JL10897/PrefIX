---
license: apache-2.0
language:
  - en
  - zh
---

# Berkeley Function Calling Leaderboard

The Berkeley function calling leaderboard is a live leaderboard to evaluate the ability of different LLMs to call functions (also referred to as tools).
We built this dataset from our learnings to be representative of most users' function calling use-cases, for example, in agents, as a part of enterprise workflows, etc.
To this end, our evaluation dataset spans diverse categories, and across multiple languages.

Checkout the Leaderboard at [gorilla.cs.berkeley.edu/leaderboard.html](https://gorilla.cs.berkeley.edu/leaderboard.html)
and our release blogs:

[BFCL V1](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html): Our initial BFCL release

[BFCL V2](https://gorilla.cs.berkeley.edu/blogs/12_bfcl_v2_live.html): Our second release, employing enterprise and OSS-contributed live data

[BFCL V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html#composition): Introduces multi-turn and multi-step function calling scenarios

**_Latest Version Release Date_**: 09/22/2024

**_Original Release Date_**: 02/26/2024

## Prepare Evaluation Dataset

To use the BFCL dataset, please follow the instructions detailed in the README [here](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard).

The BFCL dataset is organized in multiple JSON files, where each file representing a test category. Each line in the JSON file is a JSON object. You can use the following helper functions to load the dataset:

```python
def load_file(file_path: str):
    result = []
    with open(file_path) as f:
        file = f.readlines()
        for line in file:
            result.append(json.loads(line))
    return result
```

If you prefer a Hugging Face Datasets–compatible format, you can use the following helper function to convert the list of dictionaries (returned by `load_file`) into a Dataset object.

> Note: This process will convert the function parameters field into a JSON string due to its complex structure. You may need to parse them back into dictionaries during evaluation.

```python
from datasets import Dataset
import copy
import json

def load_json_dataset(test_entries: List[Dict[str, Any]]):
    data = {"id": [], "question": [], "function": []}
    test_entries_copy = copy.deepcopy(test_entries)

    for item in test_entries_copy:
        data["id"].append(item["id"])
        data["question"].append(item["question"])

        for func in item["function"]:
            func["parameters"]["properties"] = json.dumps(
                func["parameters"]["properties"]
            )
        data["function"].append(func)
    return Dataset.from_dict(data)

# Example usage
test_entries = load_file("path_to_your_file.json")
ds = load_json_dataset(test_entries)
```

## Dataset Composition

We break down our dataset into our 3 major releases. The composition of each release is as follows:

**BFCL V1**:

![image/png](https://cdn-uploads.huggingface.co/production/uploads/63814d392dd1f3e7bf59862f/IE-HwJL1OUSi-Tc2fT-oo.png)

**BFCL V2 Live**:

![image/png](https://gorilla.cs.berkeley.edu/assets/img/blog_post_12_composition.png)

**BFCL V3 Multi-Turn**:

<p align="center">
  <img src="https://gorilla.cs.berkeley.edu/assets/img/blog_post_13_data_composition.png" alt="BFCL V3 data composition"/>
</p>

### Dataset Description

## BFCL V1:

In our first release, the majority of our evaluation is broken into two categories:

- **Python**: Simple Function, Multiple Function, Parallel Function, Parallel Multiple Function
- **Non-Python**: Chatting Capability, Function Relevance Detection, REST API, SQL, Java, Javascript

#### Python

**Simple (400 AST/100 Exec)**: Single function evaluation contains the simplest but most commonly seen format, where the user supplies a single JSON function document, with one and only one function call being invoked.

**Multiple Function (200 AST/50 Exec)**: Multiple function category contains a user question that only invokes one function call out of 2 to 4 JSON function documentations. The model needs to be capable of selecting the best function to invoke according to user-provided context.

**Parallel Function (200 AST/50 Exec)**: Parallel function is defined as invoking multiple function calls in parallel with one user query. The model needs to digest how many function calls need to be made and the question to model can be a single sentence or multiple sentence.

**Parallel Multiple Function (200 AST/40 Exec)**: Parallel Multiple function is the combination of parallel function and multiple function. In other words, the model is provided with multiple function documentation, and each of the corresponding function calls will be invoked zero or more times.

Each category has both AST and its corresponding executable evaluations. In the executable evaluation data, we manually write Python functions drawing inspiration from free REST API endpoints (e.g. get weather) and functions (e.g. linear regression) that compute directly. The executable category is designed to understand whether the function call generation is able to be stably utilized in applications utilizing function calls in the real world.

#### Non-Python Evaluation

While the previous categories consist of the majority of our evaluations, we include other specific categories, namely Chatting Capability, Function Relevance Detection, REST API, SQL, Java, and JavaScript, to evaluate model performance on diverse scenarios and support of multiple programming languages, and are resilient to irrelevant questions and function documentations.

**Chatting Capability (200)**: In Chatting Capability, we design scenarios where no functions are passed in, and the users ask generic questions - this is similar to using the model as a general-purpose chatbot. We evaluate if the model is able to output chat messages and recognize that it does not need to invoke any functions. Note the difference with “Relevance” where the model is expected to also evaluate if any of the function inputs are relevant or not. We include this category for internal model evaluation and exclude the statistics from the live leaderboard. We currently are working on a better evaluation of chat ability and ensuring the chat is relevant and coherent with users' requests and open to suggestions and feedback from the community.

**Function Relevance Detection (240)**: In function relevance detection, we design scenarios where none of the provided functions are relevant and supposed to be invoked. We expect the model's output to be a non-function-call response. This scenario provides insight into whether a model will hallucinate on its functions and parameters to generate function code despite lacking the function information or instructions from the users to do so.

**REST API (70)**: A majority of the real-world API calls are from REST API calls. Python mainly makes REST API calls through `requests.get()`, `requests.post()`, `requests.delete()`, etc that are included in the Python requests library. `GET` requests are the most common ones used in the real world. As a result, we include real-world `GET` requests to test the model's capabilities to generate executable REST API calls through complex function documentation, using `requests.get()` along with the API's hardcoded URL and description of the purpose of the function and its parameters. Our evaluation includes two variations. The first type requires passing the parameters inside the URL, called path parameters, for example, the `{Year}` and `{CountryCode}` in `GET` `/api/v3/PublicHolidays/{Year}/{CountryCode}`. The second type requires the model to put parameters as key/value pairs into the params and/or headers of `requests.get(.)`. For example, `params={'lang': 'fr'}` in the function call. The model is not given which type of REST API call it is going to make but needs to make a decision on how it's going to be invoked.

For REST API, we use an executable evaluation to check for the executable outputs' effective execution, response type, and response JSON key consistencies. On the AST, we chose not to perform AST evaluation on REST mainly because of the immense number of possible answers; the enumeration of all possible answers is exhaustive for complicated defined APIs.

**SQL (100)**: SQL evaluation data includes our customized `sql.execute` functions that contain sql_keyword, table_name, columns, and conditions. Those four parameters provide the necessary information to construct a simple SQL query like `SELECT column_A from table_B where column_C == D` Through this, we want to see if through function calling, SQL query can be reliably constructed and utilized rather than training a SQL-specific model. In our evaluation dataset, we restricted the scenarios and supported simple keywords, including `SELECT`, `INSERT INTO`, `UPDATE`, `DELETE`, and `CREATE`. We included 100 examples for SQL AST evaluation. Note that SQL AST evaluation will not be shown in our leaderboard calculations. We use SQL evaluation to test the generalization ability of function calling for programming languages that are not included in the training set for Gorilla OpenFunctions-v2. We opted to exclude SQL performance from the AST evaluation in the BFCL due to the multiplicity of methods to construct SQL function calls achieving identical outcomes. We're currently working on a better evaluation of SQL and are open to suggestions and feedback from the community. Therefore, SQL has been omitted from the current leaderboard to pave the way for a more comprehensive evaluation in subsequent iterations.

**Java (100) and Javascript (50)**: Despite function calling formats being the same across most programming languages, each programming language has language-specific types. For example, Java has the `HashMap` type. The goal of this test category is to understand how well the function calling model can be extended to not just Python type but all the language-specific typings. We included 100 examples for Java AST evaluation and 70 examples for Javascript AST evaluation.

The categories outlined above provide insight into the performance of different models across popular API call scenarios, offering valuable perspectives on the potential of function-calling models.

## BFCL V2 Live:

Our second release uses real world data in order to better measure LLM function calling performance in real world uses cases. To this end, there is a greater focus on the multiple function scenario, as well as relevance/irrelevance detection. The data in BFCL V2 Live is comprised of **simple (258)**, **multiple (1037)**, **parallel (16)**, and **parallel multiple (24)** categories, similar to those described in BFCL V1. In addition to these, we have the **Relevance** category, which can be broken down into the following two subcategories.

#### Relevance Evaluation

**Irrelevance Detection (875)**: The scenario where none of the function choices provided are relevant to the user query and none should be invoked. We expect the model to not output a function call; the model can either output a message explaining why the function provided are not relevant or simply output a non-function call response (e.g., an empty list).

**Relevance Detection (41)**: The opposite of irrelevance detection. The scenario where at least one of the function choices provided are relevant to the user query and should be invoked, but the way the user prompt or the function doc is stated means that there could be infinitely many correct function calls and impossible to use a pre-defined possible answer set to evaluate. We expect the model to output some function call (one or multiple) that is relevant to the user query; we don't check for the correctness of the function call in this category (eg, correct parameter value).

## BFCL V3:

This release introduces scenarios that require multi-step function calling, where multiple internal function calls can be used to address a single user request, as well as multi-turn function calls, which involve multiple exchanges or function calls between user and assistant. Within our multi-step and multi-turn data are the following categories:

**Base Multi-Turn (200)**: This category covers the foundational yet sufficiently diverse basic multi-turn interactions. In this category, we provide complete information to call each function (either through current turn question, execution result from previous turn, or initial state configuration)

**Augmented Multi-Turn (800)**: This category introduce additional complexity, such as ambiguous prompts or situations where the model must process multiple pieces of information across turns (similar to Multihop QA), requiring models to handle more nuanced decision-making, disambiguation, and conditional logic across multiple turns.
The augmented multiturn data is comprised of the followin subcategories:

- **Missing Parameters (200)**: This dataset challenges the model to identify required missing information that cannot be retrieved elsewhere in the system. In this scenario, we expect the LLM to ask for a follow-up to clarify the misinformation. This is distinct from certain entries in the Core Multi-Turn dataset where the question has implicit intent that can be answered by referencing the backend system.

- **Missing Functions (200)**: This scenario denotes when we expect the model to recognize that no action should be taken given the lack of functions provided. If the LLM raises that concern, we then supply it with the hold-out functions that can successfully perform user intended tasks. Note that the Core dataset and the Missing Function dataset essentially contains the same sequence of actions except for the latter we hold-out a subset of functions on execution path to further challenge the model's inference ability.

- **Long-Context (200)**: This dataset challenges the model's resilience in long context scenarios on function calling. We inject random objects (e.g. hundreds of files in one directory or thousands of booking records) to mimic real world API output, which tend to be overtly informative. Here, we aim to test the model's ability to grasp the core information from an overwhelmingly large context.

- **Composite (200)**: Composite Category seeks to combine all three scenarios above to create an exceptionally hard challenge that, despite being rare, is important to handle when using autonomous agents at scale. Through this category, we want to convince the audience that a good model performance in this category offers a strong signal that LLMs can function as autonomous agents at scale despite rare and extremely difficult scenarios.

### Evaluation

This dataset serves as the question + function documentation pairs for Berkeley Function-Calling Leaderboard (BFCL) evaluation. The source code for the evaluation process can be found [here](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) with detailed instructions on how to use this dataset to compare LLM tool use capabilities across different models and categories.

More details on evaluation metrics, i.e. rules for the Abstract Syntax Tree (AST) and executable evaluation can be found in the [release blog](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html#metrics).

### Contributing

All the models, and data used to train the models are released under Apache 2.0.
Gorilla is an open source effort from UC Berkeley and we welcome contributors.
Please email us your comments, criticisms, and questions.
More information about the project can be found at https://gorilla.cs.berkeley.edu/

### BibTex

```bibtex
@misc{berkeley-function-calling-leaderboard,
  title={Berkeley Function Calling Leaderboard},
  author={Fanjia Yan and Huanzhi Mao and Charlie Cheng-Jie Ji and Tianjun Zhang and Shishir G. Patil and Ion Stoica and Joseph E. Gonzalez},
  howpublished={\url{https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html}},
  year={2024},
}
```

---

## 中文翻译

# Berkeley Function Calling Leaderboard

Berkeley Function Calling Leaderboard 是一个实时榜单，用来评估不同 LLM 的函数（也称工具）调用能力。我们基于真实经验构建了这份数据集，使其能够代表大多数用户的函数调用场景，例如智能体工作流、企业级自动化等。因此，评测数据集覆盖多种类别，并支持多种语言。

欢迎访问排行榜 [gorilla.cs.berkeley.edu/leaderboard.html](https://gorilla.cs.berkeley.edu/leaderboard.html)，以及以下版本发布博客：

[BFCL V1](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html)：首次公开版本  
[BFCL V2](https://gorilla.cs.berkeley.edu/blogs/12_bfcl_v2_live.html)：更关注企业与开源社区贡献的实时数据  
[BFCL V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html#composition)：引入多轮、多步函数调用场景

**_Latest Version Release Date_**：09/22/2024  
**_Original Release Date_**：02/26/2024

## 准备评测数据集

请参考 [README](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) 中的详细步骤使用 BFCL 数据集。

BFCL 数据集拆分成多个 JSON 文件，每个文件代表一个测试类别。JSON 文件中的每一行都是一个 JSON 对象，可以使用下面的辅助函数加载数据：

```python
def load_file(file_path: str):
    result = []
    with open(file_path) as f:
        file = f.readlines()
        for line in file:
            result.append(json.loads(line))
    return result
```

如果你偏好 Hugging Face Datasets 兼容格式，可以用下面的辅助函数把 `load_file` 返回的字典列表转换成 Dataset 对象。

> 注意：由于函数参数字段结构复杂，该过程会把 `parameters` 字段转成 JSON 字符串。评测时如需操作参数，请自行解析回字典。

```python
from datasets import Dataset
import copy
import json

def load_json_dataset(test_entries: List[Dict[str, Any]]):
    data = {"id": [], "question": [], "function": []}
    test_entries_copy = copy.deepcopy(test_entries)

    for item in test_entries_copy:
        data["id"].append(item["id"])
        data["question"].append(item["question"])

        for func in item["function"]:
            func["parameters"]["properties"] = json.dumps(
                func["parameters"]["properties"]
            )
        data["function"].append(func)
    return Dataset.from_dict(data)

# Example usage
test_entries = load_file("path_to_your_file.json")
ds = load_json_dataset(test_entries)
```

## 数据集构成

我们按三次主要发布拆分数据集，各版本构成为：

**BFCL V1**:

![image/png](https://cdn-uploads.huggingface.co/production/uploads/63814d392dd1f3e7bf59862f/IE-HwJL1OUSi-Tc2fT-oo.png)

**BFCL V2 Live**:

![image/png](https://gorilla.cs.berkeley.edu/assets/img/blog_post_12_composition.png)

**BFCL V3 Multi-Turn**:

<p align="center">
  <img src="https://gorilla.cs.berkeley.edu/assets/img/blog_post_13_data_composition.png" alt="BFCL V3 data composition"/>
</p>

### 数据集说明

## BFCL V1

首个版本的评测大体分成两大类：

- **Python**：Simple Function、Multiple Function、Parallel Function、Parallel Multiple Function
- **Non-Python**：Chatting Capability、Function Relevance Detection、REST API、SQL、Java、Javascript

#### Python

**Simple (400 AST/100 Exec)**：单函数评测是最常见的形式，用户仅提供一份 JSON 函数文档，且只会调用唯一一次函数。

**Multiple Function (200 AST/50 Exec)**：用户只会调用 2~4 份函数文档中的某一个，模型需要根据上下文挑选最合适的函数。

**Parallel Function (200 AST/50 Exec)**：同一次用户提问需要并行触发多个函数调用，问题描述可能是一句或多句，需要模型判断总共要调用多少次。

**Parallel Multiple Function (200 AST/40 Exec)**：并行与多函数结合，模型获得多份函数文档，每个函数可能被调用零次或多次。

每个类别都提供 AST 与可执行两种评测。可执行数据中，我们手写 Python 函数，灵感来自免费 REST API（如天气查询）以及直接计算型函数（如线性回归）。该类别旨在检验模型生成的函数调用能否在真实函数调用应用中稳定落地。

#### Non-Python Evaluation

除核心类别外，我们还设计了 Chatting Capability、Function Relevance Detection、REST API、SQL、Java、JavaScript 等场景，用来评估模型在多种任务及编程语言下的表现，并验证其是否能抵抗无关问题或无关函数文档的干扰。

**Chatting Capability (200)**：不提供任何函数，用户提出通用问题，接近于一般聊天机器人。我们评估模型能否只输出对话内容，并意识到无需调用函数。与 “Relevance” 不同，后者需要先判断函数是否相关。此类别仅用于内部评估，不计入线上排行榜。我们也在探索更好的聊天能力评估方法，欢迎社区反馈。

**Function Relevance Detection (240)**：所有提供的函数都不相关，也不应被调用。期望模型输出非函数调用的回答，从而观察模型是否会在缺乏信息或指令时幻觉出函数与参数。

**REST API (70)**：现实世界多数 API 都是 REST 调用，Python 会通过 `requests.get()`、`requests.post()`、`requests.delete()` 等完成调用，其中 `GET` 最常见。因此我们选取真实 `GET` 请求，通过复杂函数文档测试模型是否能生成可执行的 REST 调用。评测包含两种形态：其一是把参数放在 URL 中的 path parameters，例如 `GET /api/v3/PublicHolidays/{Year}/{CountryCode}` 中的 `{Year}` 与 `{CountryCode}`；其二是把参数放到 `requests.get(.)` 的 params 和/或 headers 中，如 `params={'lang': 'fr'}`。模型事先不会得知是哪类请求，需要自行决定调用方式。

REST API 使用可执行评测，验证调用过程是否顺利、响应类型与 JSON key 是否一致。AST 评测则因为可行答案过多（尤其在复杂 API 中）而暂未提供。

**SQL (100)**：我们自定义了 `sql.execute` 函数，包含 `sql_keyword`、`table_name`、`columns`、`conditions` 四个参数，可构造 `SELECT column_A from table_B where column_C == D` 这类查询，目的是在函数调用流程中可靠生成 SQL，而非专门训练 SQL 模型。数据集限定了简单关键字，如 `SELECT`、`INSERT INTO`、`UPDATE`、`DELETE`、`CREATE`，共 100 条 AST 样例。SQL AST 不记入排行榜，因为同一目的可能有多种构造方式。我们仍在优化 SQL 评测，也欢迎社区意见，因此暂不在排行榜展示 SQL 结果。

**Java (100) 与 Javascript (50)**：虽然函数调用格式类似，但各语言存在特有类型（如 Java 的 `HashMap`）。该类别用来检验函数调用模型能否在 Python 以外的类型体系中扩展。我们提供 100 条 Java AST 与 70 条 Javascript AST 样例。

上述类别呈现了主流 API 调用情境下不同模型的表现，有助于判断函数调用模型的潜在能力。

## BFCL V2 Live

第二次发布直接使用真实世界数据，更贴近真实用例，因此更强调多函数场景与相关性/无关性检测。数据由 **simple (258)**、**multiple (1037)**、**parallel (16)**、**parallel multiple (24)** 四类组成，并新增 **Relevance**（细分为两个子类别）。

#### Relevance Evaluation

**Irrelevance Detection (875)**：提供的所有函数都与用户问题无关，不应调用。期望模型不输出函数调用，可以给出解释或返回非函数调用（如空列表）。

**Relevance Detection (41)**：与 Irrelevance 相反。至少有一个函数与用户问题相关且应被调用，但由于提示或函数描述存在无限多的合理答案，无法事先枚举。我们只要求模型输出与问题相关的函数调用（一个或多个），不会检查参数值等细节是否完全正确。

## BFCL V3

第三个版本引入多步函数调用（一个请求需依赖多个内部调用）以及多轮对话（用户与助手之间多轮交互与函数调用）。多步与多轮数据包含以下类别：

**Base Multi-Turn (200)**：覆盖基础但多样的多轮交互场景，在每个步骤里我们都会提供足够的信息（来自当前问题、上一轮返回或初始状态）。

**Augmented Multi-Turn (800)**：进一步提升难度，例如提示含糊或需要跨轮整合多段信息（类似 Multihop QA），迫使模型在多轮中完成更复杂的推理、消歧和条件逻辑。

增强版又拆成以下子类：

- **Missing Parameters (200)**：故意缺少必须的参数，且无法从系统其它地方获得，期望模型主动追问补全。这区别于 Base Multi-Turn 中可以依赖后台隐式信息的情况。
- **Missing Functions (200)**：缺失必要函数，期望模型识别出 “无法行动”，并在提出疑问后获取保留的函数文档。该子集与 Base 的执行路径类似，只是人为拿掉了一部分函数以挑战模型推断能力。
- **Long-Context (200)**：注入大段上下文（如包含数百文件或成千上万条记录的输出），测试模型在冗长内容中抓住核心信息的能力。
- **Composite (200)**：综合上述三种困难场景，打造极具挑战但在大规模自动化智能体中必须处理的极端情况，验证模型在罕见难题中的稳健性。

### 评测

该数据集提供 BFCL 评测所需的 “问题 + 函数文档” 对。评测代码位于 [GitHub 仓库](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard)，其中包含如何使用这些数据比较不同模型工具调用能力的详细说明。

关于 AST 规则与可执行评测指标的更多细节，请查阅 [发布博客](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html#metrics)。

### 参与贡献

所有模型与训练数据均以 Apache 2.0 协议发布。Gorilla 是来自 UC Berkeley 的开源项目，欢迎各界贡献者。若有意见、批评或问题，欢迎发送邮件。更多项目信息见 https://gorilla.cs.berkeley.edu/

### BibTex

```bibtex
@misc{berkeley-function-calling-leaderboard,
  title={Berkeley Function Calling Leaderboard},
  author={Fanjia Yan and Huanzhi Mao and Charlie Cheng-Jie Ji and Tianjun Zhang and Shishir G. Patil and Ion Stoica and Joseph E. Gonzalez},
  howpublished={\url{https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html}},
  year={2024},
}
```
