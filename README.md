# SmartCLI

SmartCLI 是一个面向开发者、本地优先的终端 AI 助手。它读取问题、代码、日志和命令输出，提供解释、审查、排错和多轮追问，并可将结果保存为可检索的本地知识记录。

SmartCLI 需要 Python 3.11 或更高版本。它只分析文本，不会自动执行模型生成的命令。

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

内置模型别名为 `deepseek`、`glm`、`openai` 和 `ollama`。云端模型分别设置对应环境变量：

```text
DEEPSEEK_API_KEY=...
GLM_API_KEY=...
OPENAI_API_KEY=...
```

`ollama` 默认连接 `http://localhost:11434/v1` 并使用 `qwen2.5:7b`，不需要 API Key。可通过 `OLLAMA_BASE_URL` 和 `OLLAMA_MODEL` 覆盖；其他供应商也支持同名规则，例如 `OPENAI_BASE_URL`、`OPENAI_MODEL`。

## ReAct Agent

```bash
smartcli agent "检查当前项目并总结测试风险" --model ollama --verbose
smartcli agent "读取 pyproject.toml 并解释依赖" --workspace .
git diff | smartcli agent "审查这些修改" --model deepseek
```

Agent 使用 Thought → Action → Observation 闭环，内置 shell、文件读写和笔记检索工具；最大步数默认为 12。详细 JSON 工具调用协议、关键类结构和安全规则见 [AGENT_PROTOCOL.md](AGENT_PROTOCOL.md)。高危 shell 操作必须在交互终端二次确认，禁止级操作始终拒绝；自动化任务只有显式传入 `--approve-risky` 才会预授权高危操作。

也可以放入当前目录或父目录的 `.env`。API Key 不会写入用户配置或由 `config show` 显示。内置 API 模型 ID 是兼容接口的合理默认值，供应商调整接口后可能需要修改源码中的集中模型注册表。本项目的测试不会访问网络或验证付费模型。

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
- 单次回答默认最多生成 2,048 tokens；供应商因长度停止时会在 stderr 明确提示回答可能不完整。
- 对话不能跨进程恢复。
- 笔记采用单个 JSON 文件，适合个人和中小规模数据。
- 模型可用性取决于供应商的 OpenAI 兼容接口、账户权限和当前模型 ID。
