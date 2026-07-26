# SmartCLI 技术架构

## 1. 系统概览

SmartCLI 采用 Python `src` 布局，CLI、模型服务、Agent 编排、工具执行和本地存储相互分离。

```text
CLI / JSON contract
  |-- ask / chat -----------------> LLMService
  |-- note / config --------------> JSON storage + process lock
  `-- agent ----------------------> ReActAgent
                                      |-- ShortTermMemory
                                      |-- ToolRegistry
                                      |     |-- files / git / notes
                                      |     `-- project checks
                                      `-- AuditLogger
```

## 2. 主要模块

- `smartcli.cli`：参数解析、命令分发、JSON 契约、交互确认和错误出口；
- `smartcli.services.llm`：ModelProfile、OpenAI 兼容适配、超时与重试；
- `smartcli.agent`：严格 JSON 决策协议和有界 ReAct 循环；
- `smartcli.tools`：工具 Schema、风险分级、权限与具体执行器；
- `smartcli.commands.note`：本地知识记录；
- `smartcli.config`：非敏感默认值和模型 Profile；
- `smartcli.storage`：Windows/POSIX 跨进程文件锁；
- `smartcli.runs`：运行报告、文件检查点和哈希保护撤销；
- `smartcli.audit`：隐私友好的 JSONL 工具审计；
- `smartcli.output_style` / `rendering`：Markdown 规范化和终端渲染。

## 3. Agent 协议

每轮模型必须返回一个 JSON 对象，并且只能包含 `action` 或 `final` 之一。运行器对工具名、参数
Schema、风险、授权和 dry-run 逐层检查。工具 observation 最多保留 12,000 字符，Agent 短期记忆
同时受事件数和字符数约束。任务超过 40,000 字符时明确拒绝，避免每轮发送超大输入。

内部 `thought` 只允许简短决策摘要，不输出到普通或 verbose 用户界面。

## 4. 工具安全

文件工具将路径限制在 workspace 内，拒绝敏感文件、`.git`、符号链接写入和超大正文。
覆盖文件需要当前 SHA-256，实现乐观并发控制。

`apply_patch` 使用有序精确文本替换。每个替换声明旧文本、新文本和预期出现次数；文件哈希、
替换数量或 UTF-8 解码任一不满足时整体失败，不产生部分 Patch。

Git 工具只构造枚举化只读参数数组，不通过 shell。项目检查工具也直接构造参数数组：

- `tests`：`python -m pytest`
- `lint`：`python -m ruff check .`
- `compile`：`python -m compileall -q src tests`

项目检查可能执行仓库代码，因此风险为 `high`，必须显式开放能力并逐次确认。
检查进程只继承运行所需的基础环境变量，不继承 API Key 等敏感变量。当前实现不提供操作系统级
文件或网络隔离，因此不能把 `--allow check` 用于不可信仓库；后续应接入容器或宿主沙箱。

## 5. 存储一致性

笔记和配置使用 UTF-8 JSON 与同目录原子替换。写事务在目标文件旁取得跨进程排他锁，并在锁内
重新读取最新数据，然后修改和替换，避免多个进程基于旧快照互相覆盖。Windows 使用
`msvcrt.locking`，POSIX 使用 `fcntl.flock`。

该方案适合个人和中小规模数据。查询量、并发或记录数量显著增加后应迁移到 SQLite/FTS5。

## 6. 审计语义

有副作用动作执行前记录授权与待执行状态，执行后记录结果。执行前审计失败时动作不会开始；
执行后审计失败时保留真实工具结果并附加警告，避免 Agent 因误判失败而重复执行副作用。

审计参数只保存字段名、目标路径和参数哈希，不保存文件正文。

## 7. 运行报告与撤销

CLI Agent 启动时创建唯一 `run_id`。报告记录任务哈希与短预览、workspace、工具动作摘要、工具
结果元数据、最终计划和状态。文件写入前，RunJournal 将修改前正文和权限保存到用户数据目录；
公开报告会过滤正文和权限。

撤销按变更的逆序执行。开始前验证每个文件仍匹配该运行最后写入的 SHA-256；不匹配时拒绝整个
撤销。已有文件通过同目录临时文件原子恢复，新建文件仅在哈希匹配时删除。单个文件检查点上限
为 1,000,000 字节。

## 8. 上下文控制

- stdin 单次上限：100,000 字符；
- Agent 任务上限：40,000 字符；
- 单条 Chat 消息上限：20,000 字符；
- Chat 请求历史预算：60,000 字符；
- 工具 observation 上限：12,000 字符；
- Agent 短期记忆默认上限：24 个事件/24,000 字符。

当前采用字符预算，不等价于模型 token。后续应引入模型感知 token 估算和旧历史结构化摘要。

## 9. 测试与发布

测试覆盖 CLI 契约、Agent 协议、权限确认、文件安全、Git 参数构造、模型重试、存储失败回滚、
并发快照合并、上下文预算、审计异常和 Markdown 输出。CI 在 Windows/Linux 与多个 Python 版本上
执行 Ruff、pytest、构建、wheel 安装、CLI smoke test 和 `pip check`。

发布元数据位于 `pyproject.toml`，控制台入口为 `smartcli = smartcli.cli:main`。
