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
│   ├── ShellTool ── ShellSafetyPolicy
│   ├── ReadFileTool
│   ├── WriteFileTool
│   └── NoteSearchTool
├── ShortTermMemory
└── LongTermMemory (Protocol)
    └── NullLongTermMemory
```

- `Tool`：声明名称、描述、输入 JSON Schema、风险等级和执行方法。
- `ToolRegistry`：负责注册、发现和防止重名。
- `ReActAgent`：限制最大步数、模型重试次数和连续失败次数，执行协议校验与工具安全检查。
- `ShortTermMemory`：按事件数和字符数双重限制保留最近上下文。
- `LongTermMemory`：为向量库预留 `search/store` 接口，当前默认实现不持久化。

## Shell 安全规则

命令分为 `safe`、`review`、`high`、`blocked`：

- `blocked`：格式化磁盘、分区操作、根目录递归删除等，始终拒绝。
- `high`：删除、提权、破坏性 Git 操作、关机、下载后执行，必须由用户交互确认；非交互输入默认拒绝。
- `review`：覆盖重定向、移动文件、修改权限和依赖安装。
- `safe`：未命中危险模式的只读或普通命令。

`--approve-risky` 是自动化场景下的显式预授权，调用方需自行承担高危命令后果。文件工具始终将路径限制在 `--workspace` 内。

## 系统提示词

模板位于 `src/smartcli/agent/prompts.py`。运行时将工具注册表的名称、说明、参数结构和风险等级序列化到 `{tool_specs}`，确保模型看到的能力描述与实际执行器一致。
