# SmartCLI

SmartCLI 是一个安全、可审计、模型可替换的本地代码变更 Agent。它读取问题、代码、日志和命令输出，在明确授权范围内检查仓库、修改文件、运行批准的项目检查，并可将结果保存为可检索的本地知识记录。

SmartCLI 需要 Python 3.11 或更高版本。`ask` 和 `chat` 只分析文本；`agent` 默认只读，只能在用户显式授权后写入工作区文件或执行枚举化项目检查。SmartCLI 不向模型提供通用 shell 或网络执行能力。产品设计见 [PRODUCT_DESIGN.md](PRODUCT_DESIGN.md)，实现架构见 [TECHNICAL_ARCHITECTURE.md](TECHNICAL_ARCHITECTURE.md)。

## 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
```

开发环境：

```bash
conda activate agent_dev
python -m pip install -e ".[dev]"
```

## 模型与 API Key

内置 ModelProfile 为 `deepseek`、`glm`、`openai` 和 `ollama`。云端模型分别设置对应环境变量：

```text
DEEPSEEK_API_KEY=...
GLM_API_KEY=...
OPENAI_API_KEY=...
```

`deepseek` 默认使用 `deepseek-v4-flash`。`ollama` 默认连接 `http://localhost:11434/v1` 并使用 `qwen2.5:7b`，不需要 API Key。可通过 `OLLAMA_BASE_URL` 和 `OLLAMA_MODEL` 覆盖；其他供应商也支持同名规则，例如 `DEEPSEEK_MODEL`、`OPENAI_BASE_URL`、`OPENAI_MODEL`。

自定义 ModelProfile 只保存非敏感配置，API Key 仍由环境变量提供：

```bash
smartcli model add localdev --provider ollama --model-id qwen3:8b \
  --base-url http://localhost:11434/v1 --timeout 90 --connect-timeout 5 --retries 2
smartcli model list
smartcli model show localdev
smartcli config set default_model localdev
smartcli model remove localdev
```

Profile 可配置 `max_tokens`、temperature、总超时、连接超时和重试次数。只对连接错误、超时、HTTP 429 与 5xx 进行指数退避重试；认证、模型名和请求参数错误立即返回。每个 profile 可用其大写名称覆盖模型和端点，例如 `LOCALDEV_MODEL`、`LOCALDEV_BASE_URL`。

## 环境诊断

```bash
smartcli doctor
smartcli doctor --model ollama --json
smartcli doctor --model deepseek --connect
```

`doctor` 默认离线检查 Python、配置、数据目录、ModelProfile 和 API Key 是否就绪。`--connect` 会发送一次最小模型请求，可能产生供应商用量。

## JSON 输出

```bash
smartcli ask "解释 descriptor" --json
smartcli agent "检查项目" --json
smartcli note list --json
smartcli model list --json
smartcli doctor --json
smartcli eval run evals/cases --json
```

成功响应使用 `{"ok":true,"command":"...","data":...}`；运行时错误使用 `{"ok":false,"command":"...","error":{"type":"...","message":"..."}}` 并返回非零退出码。交互式 `chat` 不支持 JSON 输出。

## 终端 Markdown 输出

`ask`、`chat`、`agent` 和保存的 AI 笔记统一使用轻量 Markdown。模型提示会要求只使用三级标题、扁平列表、局部加粗和单行反引号，并避免代码围栏、表格、引用、分隔线和深层列表。

交互终端中的回答由 Rich 渲染，标题使用紧凑的青色竖线标记，列表、加粗和行内代码使用统一的强调样式。标题与正文之间不会插入多余空行，括号内的短英文术语会尽量保持在同一行。输出重定向到文件或管道时保留原始 Markdown，便于保存和后续处理。`--json` 是面向脚本的机器输出模式，始终保持未渲染的标准 JSON。

模型响应在显示或保存前还会经过规范化：标题统一为 `###`，表格转换为扁平列表，连续空行压缩为一个，代码围栏和多余结构标记会被移除。JSON 输出结构保持不变，其中的 `answer` 和 `final` 文本字段遵循相同规则。

Agent 的内部决策不会写入普通输出或 `--verbose` 输出。详细模式只显示工具动作与观察，最终结果可直接用于 Rich 终端渲染，也可保存为普通文本。

## ReAct Agent

```bash
smartcli agent "检查当前项目并总结测试风险" --model ollama --verbose
smartcli agent "读取 pyproject.toml 并解释依赖" --workspace .
git diff | smartcli agent "审查这些修改" --model deepseek
smartcli agent "生成测试配置" --allow write --dry-run
smartcli agent "检查当前 Git 修改" --allow git
smartcli agent "生成修复文件" --allow write
smartcli agent "运行测试并分析失败" --allow check
smartcli run list
smartcli run show RUN_ID
smartcli run undo RUN_ID
```

Agent 使用 Thought → Action → Observation 闭环，最大步数默认为 12。默认只开放项目结构发现、工作区文件读取和笔记检索。`--allow git` 增加固定的只读 Git 操作，`--allow write` 增加受控文件写入，`--allow check` 增加 `tests`、`lint`、`compile` 三种项目检查；写入和检查都必须逐次交互确认，`--approve-risky` 不能跳过该确认。`--dry-run` 可以读取上下文，但跳过有副作用的工具。

Git 工具只接受 `status`、`diff`、`log`、`show`、`ls_files` 枚举操作，由程序构造参数数组并直接启动 Git。项目检查同样由程序构造参数数组，不解释 shell 语法；由于测试可能执行仓库代码，其风险等级为 high 并要求确认，且不会继承 API Key 等敏感环境变量。Local 后端不是操作系统沙箱，只适用于可信仓库；Docker 后端使用只读能力裁剪、非 root 用户、资源限制、单一 workspace 挂载和 `network=none`，配置失败时不会降级到 Local。`shell` 和 `network` 不属于模型可直接调用的工具能力。

写文件始终限制在 workspace 内，拒绝符号链接、凭据和 `.git` 内部路径，单次上限为 1,000,000 字节。覆盖已有文件时，模型必须提交此前读取内容的 SHA-256；内容发生变化时写入会失败。最终提交使用同目录临时文件和原子替换。

Agent 优先使用 `apply_patch` 对现有 UTF-8 文件做精确文本替换。Patch 必须提交当前文件 SHA-256，且每个旧文本的实际出现次数必须与声明一致；任一条件不满足时不会产生部分修改。

每次 Agent 运行都会生成 `run_id`，并在用户数据目录的 `smartcli/runs` 保存结构化报告。文件修改前会保存本地检查点；`run undo` 只在当前文件仍匹配 Agent 写入后哈希时恢复，避免覆盖用户后续编辑。检查点包含修改前正文，但不会进入审计日志，也不会由 `run show` 输出。

Agent 工具动作默认记录到用户数据目录的 `smartcli/audit.jsonl`。审计记录包含风险、授权和执行结果，只保存参数键、目标路径及参数哈希，不保存命令或文件正文；测试时可通过 `SMARTCLI_AUDIT_PATH` 覆盖位置。详细协议和安全规则见 [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md)。

## 项目策略与隔离执行

在 workspace 根目录创建 `smartcli.toml`。策略只能收紧 `--allow` 已授予的权限，不能自行开放写入、检查、Git 或网络能力。完整示例也见 [smartcli.example.toml](smartcli.example.toml)：

```toml
[execution]
backend = "docker"
image = "smartcli-project:py311"
network = "none"
timeout_seconds = 120
memory_mb = 512
cpus = 1.0
pids_limit = 128

[workspace]
writable = ["src/**", "tests/**", "docs/**"]
protected = [".github/**", "migrations/**"]

[checks]
allowed = ["tests", "lint", "compile"]
required = ["tests", "lint"]
```

0.9.0 只接受 `network = "none"`。Docker 镜像必须由用户预先构建或拉取；SmartCLI 不自动拉取镜像，也不会在 Docker CLI、daemon 或镜像不可用时转用本机执行。

## 验证证据与遥测

运行报告从真实工具动作推导 `verified`、`partially_verified`、`failed` 或 `unverified`。只有最后一次成功文件修改之后运行并通过的检查才有效；后续写入会使旧检查证据失效。最终模型步骤会收到机器生成的证据块，普通输出在 stderr 显示状态，JSON 和 `run show` 返回完整检查、后端、退出码与变更文件。

本地遥测记录总耗时、模型调用与重试、供应商返回的 token 用量、工具耗时/成功率、输出截断、协议错误和审批拒绝。供应商不返回 usage 时 token 字段为 `null`，不会伪造精确计数。遥测不接收提示词、文件正文或工具参数。

## 离线 Agent 评测

```bash
smartcli eval run evals/cases
smartcli eval run evals/cases --json
smartcli eval report EVAL_REPORT_ID --json
# 只有显式指定后才调用真实模型
smartcli eval run path/to/cases --model ollama
```

案例由 `case.json` 和 `fixture/` 组成。默认脚本化决策通过真实 ReAct 循环在一次性 workspace 中执行，并确定性评分运行状态、验证检查、预期/禁止变更路径、文件包含/排除断言、步数预算和权限越界；聚合 JSON 与 Markdown 报告保存在用户数据目录的 `smartcli/evals`。

案例声明 `check` 能力时必须在 fixture 的 `smartcli.toml` 中配置 Docker 后端；eval 不会自动批准 Local 检查，因为一次性目录并不能隔离宿主文件和网络。fixture 中的符号链接会被拒绝。

也可以放入当前目录或父目录的 `.env`。API Key 不会写入用户配置、ModelProfile 或由 `config show` 显示。本项目的自动化测试不会访问网络或验证付费模型。

## 单次分析

```bash
smartcli ask "解释 Python descriptor"
smartcli ask "解释这段代码" --role code --model deepseek
Get-Content error.log | smartcli ask "分析这个错误" --role debug
git diff | smartcli ask "审查这些修改" --role review
smartcli ask "解释装饰器" --save --tag python
```

没有位置参数时也可只读取 stdin。问题与 stdin 同时存在时，SmartCLI 会用独立的“用户指令”和“标准输入”区段发送给模型。stdin 上限为 100,000 个字符。

可用角色：`default`、`code`、`review`、`debug`、`summary`、`translate`。

## 多轮对话

```bash
smartcli chat --role debug
```

输入 `exit`、`quit` 或 `q` 结束。对话上下文只保留在当前进程中；请求失败不会丢失此前的成功历史。单条消息上限为 20,000 字符，请求历史预算为 60,000 字符，超过预算时保留系统提示和最新完整轮次。
按 `Ctrl+C` 或发送 EOF 也会正常结束聊天，不显示 Python traceback。

## 本地知识记录

```bash
smartcli note add "descriptor 是实现 __get__ 的对象" --tag python
smartcli note list
smartcli note show NOTE_ID
smartcli note search python
smartcli note delete NOTE_ID
```

手动笔记标记为 `manual`，`ask --save` 产生的笔记标记为 `ai`，并记录所用模型和角色。搜索覆盖标题、正文和标签且忽略大小写。

默认数据位置由 `platformdirs` 决定：笔记位于用户数据目录的 `smartcli/notes.json`，配置位于用户配置目录的 `smartcli/config.json`。写事务使用跨进程锁，在锁内重新加载最新数据，然后通过临时文件和原子替换提交。

## 配置

```bash
smartcli config show
smartcli config set default_model glm
smartcli config set default_role review
```

只允许修改 `default_model` 和 `default_role`。命令行的 `--model`、`--role` 优先于保存的默认值。

## 开发与验证

```bash
python -m compileall -q src tests
python -m pytest
python -m ruff check .
python -m build
smartcli --help
smartcli --version
smartcli eval run evals/cases --json
```

Docker 集成测试为显式 opt-in，并要求镜像已存在：

```powershell
$env:SMARTCLI_DOCKER_TEST="1"
$env:SMARTCLI_DOCKER_IMAGE="python:3.11-slim"
python -m pytest tests/test_docker_integration.py -v
```

## 已知限制

- 不提供流式输出。
- 内置 Profile 单次回答默认最多生成 2,048 tokens；自定义 Profile 可以调整。
- 对话不能跨进程恢复。
- 上下文预算当前按字符计算，尚未按具体模型 token 精确估算。
- 笔记采用带跨进程写锁的单个 JSON 文件，适合个人和中小规模数据。
- 模型可用性取决于供应商的 OpenAI 兼容接口、账户权限和当前模型 ID。
- 只支持枚举化 Python 项目检查；不支持安装依赖、任意 shell、Agent 网络工具或 Git 写命令。
- Docker 后端不负责构建或拉取镜像；Local 后端不提供操作系统级隔离。
- JSONL 审计日志当前不会自动轮转。
- 多文件撤销逐文件原子恢复，但不具备跨文件系统事务语义。
