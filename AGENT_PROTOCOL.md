# SmartCLI Agent 协议

## ReAct 响应

模型每轮必须只返回一个 JSON 对象，不允许附带 Markdown。运行时不会把详细隐藏思维过程展示给用户；`thought` 仅保存简短的决策摘要。

调用工具：

```json
{
  "thought": "需要先读取项目配置",
  "plan": ["读取配置", "检查依赖", "总结结果"],
  "action": {
    "tool": "read_file",
    "arguments": {"path": "pyproject.toml", "max_chars": 20000}
  }
}
```

结束任务：

```json
{
  "thought": "已取得完成任务所需的信息",
  "plan": [],
  "final": "最终答复"
}
```

`action` 与 `final` 必须且只能出现一个。工具参数必须符合注册工具公开的 `input_schema`。运行时会把执行结果作为 `observation` 加入滑动上下文，然后开始下一轮 Thought → Action → Observation。

## 关键类结构

```text
ReActAgent
├── LLMService
│   ├── OpenAICompatibleAdapter
│   └── OllamaAdapter
├── ToolRegistry
│   ├── GitTool (structured, read-only)
│   ├── ReadFileTool
│   ├── WriteFileTool
│   ├── NoteSearchTool
│   └── ProjectCheckTool -> Local/Docker ExecutionBackend
├── ShortTermMemory
├── TelemetryCollector
├── VerificationSummary
└── LongTermMemory (Protocol)
    └── NullLongTermMemory
```

- `Tool`：声明名称、描述、输入 JSON Schema、所需能力、风险等级、副作用和执行方法。
- `ToolRegistry`：负责注册、发现和防止重名。
- `ReActAgent`：限制最大步数、模型重试次数和连续失败次数，执行协议校验与工具安全检查。
- `ShortTermMemory`：按事件数和字符数双重限制保留最近上下文。
- `LongTermMemory`：为向量库预留 `search/store` 接口，当前默认实现不持久化。

## 能力安全规则

Agent 默认注册 `list_files`、`read_file` 和 `note_search`。`--allow git` 开放固定的只读 Git 操作，`--allow write` 开放受控 `write_file` 和 `apply_patch`，`--allow check` 开放 `tests`、`lint`、`compile` 三种枚举化项目检查；未注册的能力对模型不可见。通用 shell 和网络能力不提供。`--dry-run` 允许只读工具执行，但跳过具有副作用的工具。

文件工具将路径限制在 `--workspace` 内并拒绝常见凭据、`.git` 内部路径和符号链接。所有写入均为 `review` 风险并要求逐次确认，`--approve-risky` 不适用于写文件；覆盖还需要匹配当前文件 SHA-256。Git 工具不接收命令文本，只执行程序构造的只读参数数组，并禁用全局/系统 Git 配置和外部 diff。项目检查不经过 shell，但可能执行仓库代码，因此属于 `high` 风险并要求逐次确认。

workspace 根目录的 `smartcli.toml` 在硬编码安全规则和 CLI 能力授权之后生效，只能进一步收紧可写路径、保护路径、允许/必需检查和执行资源。Local 后端适用于可信仓库；Docker 后端关闭网络、移除 Linux capabilities、使用非 root 用户和资源限制，且任何 Docker 错误都不会触发 Local 回退。

`apply_patch` 只执行精确文本替换，不接收 shell patch 命令。运行器在写工具执行前保存本地检查点，并把 `run_id` 写入审计事件。检查点正文与审计日志分离，撤销前必须匹配写入后的 SHA-256。

每次工具授权和执行结果写入 JSONL 审计日志。参数只记录字段名、目标路径和 SHA-256 摘要，不记录命令或正文原文。

最终步骤会收到由动作日志生成的 verification evidence。只有最后一次成功写入后的检查才有效，模型不得超出证据声称测试通过。运行遥测仅记录次数、耗时、成功状态、后端和供应商 token usage，不接受 prompt、文件正文或工具参数。

离线 eval 使用版本化 `case.json`、一次性 fixture 和脚本化决策驱动同一个 ReActAgent；自动批准仅限案例声明的 capabilities 与临时 workspace。真实模型评测必须在 CLI 显式指定 `--model`。
eval 中的检查只允许 Docker 后端，fixture 符号链接会被拒绝；未知/未授权工具尝试由运行时记录并进入权限 grader。

## 系统提示词

模板位于 `src/smartcli/agent/prompts.py`。运行时将工具注册表的名称、说明、参数结构和风险等级序列化到 `{tool_specs}`，确保模型看到的能力描述与实际执行器一致。
