# SmartCLI

SmartCLI 是一个面向开发者、本地优先的终端 AI 助手。它读取问题、代码、日志和命令输出，提供解释、审查、排错和多轮追问，并可将结果保存为可检索的本地知识记录。

SmartCLI 需要 Python 3.11 或更高版本。`ask` 和 `chat` 只分析文本；`agent` 默认只读，只能在用户显式授权后写入工作区文件。SmartCLI 不向模型提供通用 shell 或网络执行能力。

## 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
```

开发环境：

```bash
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
```

Agent 使用 Thought → Action → Observation 闭环，最大步数默认为 12。默认只开放项目结构发现、工作区文件读取和笔记检索。`--allow git` 增加固定的只读 Git 操作，`--allow write` 增加受控文件写入；所有文件创建和覆盖都必须逐次交互确认，`--approve-risky` 不能跳过该确认。`--dry-run` 可以读取上下文，但跳过文件写入。

Git 工具只接受 `status`、`diff`、`log`、`show`、`ls_files` 枚举操作，由程序构造参数数组并直接启动 Git，不解释 shell 语法、不运行网络操作或修改命令。`shell` 和 `network` 不属于可授权能力。

写文件始终限制在 workspace 内，拒绝符号链接、凭据和 `.git` 内部路径，单次上限为 1,000,000 字节。覆盖已有文件时，模型必须提交此前读取内容的 SHA-256；内容发生变化时写入会失败。最终提交使用同目录临时文件和原子替换。

Agent 工具动作默认记录到用户数据目录的 `smartcli/audit.jsonl`。审计记录包含风险、授权和执行结果，只保存参数键、目标路径及参数哈希，不保存命令或文件正文；测试时可通过 `SMARTCLI_AUDIT_PATH` 覆盖位置。详细协议和安全规则见 [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md)。

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

输入 `exit`、`quit` 或 `q` 结束。对话上下文只保留在当前进程中；请求失败不会丢失此前的成功历史。
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

默认数据位置由 `platformdirs` 决定：笔记位于用户数据目录的 `smartcli/notes.json`，配置位于用户配置目录的 `smartcli/config.json`。写入使用临时文件和原子替换。

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
pytest
ruff check .
python -m build
smartcli --help
smartcli --version
```

## 已知限制

- 不提供流式输出。
- 内置 Profile 单次回答默认最多生成 2,048 tokens；自定义 Profile 可以调整。
- 对话不能跨进程恢复。
- 笔记采用单个 JSON 文件，适合个人和中小规模数据。
- 模型可用性取决于供应商的 OpenAI 兼容接口、账户权限和当前模型 ID。
- 不支持运行测试、安装依赖或其他任意项目命令；这类能力需要由宿主 CI 或独立操作系统沙箱提供。
- JSONL 审计日志当前不会自动轮转。
