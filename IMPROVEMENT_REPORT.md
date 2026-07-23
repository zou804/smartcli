# SmartCLI 改进报告

## 1. 改造前的问题

- 产品范围混杂了 AI 问答、天气、计时器和简单记事，开发者工作流定位不清晰。
- CLI 使用持续增长的 `if/elif` 分发，缺少独立 `chat`、`config`、笔记查看和删除命令。
- `ask` 不读取 stdin；旧聊天每轮都丢失历史，并非真正的多轮会话。
- 角色列表分散且不一致，未知模型会静默回退；LLM 层把所有异常伪装成普通回答。
- 笔记依赖当前工作目录、直接覆写 JSON、字段不足，且通过修改 `sys.path` 支持直接运行。
- 依赖文件包含本机 Conda 绝对路径和项目自身 Git 引用，项目元数据和 README 已失真或乱码。
- 没有自动化测试，也没有明确的数据损坏、空响应和错误退出行为。

## 2. 收缩范围的原因

项目现在聚焦“输入、分析、对话、沉淀、复用”：问题和命令输出进入统一 LLM 接口，结果可进入本地知识记录。天气和计时器既不复用该流程，也引入额外网络、缓存和交互维护成本，因此删除后边界更清楚、更容易测试，且默认不会执行任何 AI 生成的命令。

## 3. 删除的功能与代码

- 删除 `weather` 和 `timer` 顶层命令及对应命令模块。
- 删除天气专用 HTTP 请求和缓存工具。
- 删除 `WeatherData` 数据模型。
- 删除 README 中所有天气和计时器说明。
- 删除本机绑定的依赖快照，重建简洁兼容 `requirements.txt`。

## 4. 实际完成功能

- 顶层 CLI：`ask`、`chat`、`note`、`config`、`--help`、`--version`。
- `ask` 支持问题、stdin、问题与 stdin 组合，stdin 上限 100,000 字符；支持模型、角色、标签和 `--save`。
- `chat` 保存当前进程的 system/user/assistant 历史，忽略空输入，支持三种退出词，并可在单轮请求失败后继续。
- 集中提供 `default`、`code`、`review`、`debug`、`summary`、`translate` 六种角色。
- OpenAI 兼容 LLM 服务接收结构化 messages，明确区分配置、请求和空响应错误。
- 本地笔记支持 add/list/show/search/delete，区分 manual/ai，兼容旧版四字段记录。
- 配置支持 `default_model`、`default_role`，不保存或显示 API Key。
- JSON 使用 UTF-8、临时文件和原子替换；笔记和配置均允许注入自定义路径。

## 5. 关键设计决策

- 使用 `argparse.set_defaults(handler=...)` 分发命令，让 CLI 展示负责、业务层返回数据或抛出异常。
- 模型注册集中在 `config.py`，角色提示集中在 `services/prompts.py`，避免多份不一致 choices。
- 单次分析和多轮聊天都调用 `LLMService.request(messages)`，减少行为分叉。
- 保持单 JSON 文件存储，符合当前个人工具规模；通过原子替换降低中断导致的数据损坏风险。
- 保留 `ask --chat` 兼容入口并输出迁移提示，不继续扩展该旧接口。
- 不实现流式输出和跨进程会话，避免显著扩大本次范围。

## 6. 文件变更

新增：

- `LICENSE`
- `IMPROVEMENT_REPORT.md`
- `tests/test_cli.py`
- `tests/test_chat.py`
- `tests/test_llm.py`
- `tests/test_storage.py`

重点修改：

- `src/smartcli/cli.py`
- `src/smartcli/commands/ask.py`
- `src/smartcli/commands/note.py`
- `src/smartcli/services/llm.py`
- `src/smartcli/services/prompts.py`
- `src/smartcli/config.py`
- `src/smartcli/models.py`
- `pyproject.toml`、`requirements.txt`、`README.md`

删除：

- `src/smartcli/commands/weather.py`
- `src/smartcli/commands/timer.py`
- `src/smartcli/utils/http.py`
- `src/smartcli/utils/cache.py`

## 7. 测试与验证结果

全部验证使用用户指定的 `C:\Users\zou\miniconda3\envs\agent_dev\python.exe`（Python 3.11.15）。未发起真实模型请求或真实网络测试。

- `python -m compileall -q src tests`：退出码 0。由于仓库旧 `__pycache__` 由隔离账户持有，使用 `PYTHONPYCACHEPREFIX` 将本次字节码写入系统临时目录。
- `python -m pytest`：收集 35 项，最终运行 `35 passed in 1.09s`。
- `python -m ruff check .`：`All checks passed!`。
- `python -m build --no-isolation`：成功生成 `smartcli-0.2.1.tar.gz` 和 `smartcli-0.2.1-py3-none-any.whl`，最终运行无许可证弃用警告。
- `smartcli --help`：退出码 0，仅显示 ask/chat/note/config 四组顶层命令。
- `smartcli --version`：退出码 0，输出 `smartcli 0.2.1`。
- 临时目录 note/config 工作流：add、list、search、config set、config show 全部退出码 0，且 config show 只显示两个非敏感配置项。
- mock AI 工作流抽查：stdin 组合、ask 保存、chat 多轮历史共 3 项，`3 passed in 0.95s`。
- `git diff --check`：退出码 0，无空白错误。

## 8. 未完成事项

- 未验证真实供应商 API：任务明确禁止真实付费请求和真实网络测试。
- 未实现流式输出：会扩大 LLM 和 CLI 输出协议，本次收益不足以覆盖改动风险。
- 未实现跨进程聊天恢复：任务明确不要求，且不应为此引入数据库。

## 9. 已知限制

- 内置模型 ID 可能随供应商接口变化，需要维护者按实际账户能力调整。
- stdin 按字符数限制，并未进行 token 级预估。
- 单 JSON 文件适合个人和中小规模记录，不适合并发多进程高频写入。
- 当前会话历史随进程退出而清除。
- 工作区内忽略的旧 `__pycache__` 受宿主 ACL 保护，无法在本次会话删除；不进入版本控制，也不影响验证和发行物。

## 10. 后续建议

1. 高：在 CI 中固定 Python 3.11/3.12，执行 pytest、Ruff 和构建。
2. 中：根据真实使用反馈增加可选流式输出，并为中断和 stderr 行为补测试。
3. 中：为超长输入增加可配置限制或 token 预估，但仍默认拒绝而非静默截断。
4. 低：数据量明显增长后再评估文件锁或分片，不提前引入数据库。

## 11. 当前状态与可用性

SmartCLI 已形成可安装、可测试的 0.2.1 版本。该版本将默认回答上限提升到 2,048 tokens，增加输出截断提示和聊天友好中断，并保证笔记写入失败时内存状态不被提前修改。核心 CLI、离线测试、构建元数据和开发文档一致；在正确配置 API Key 且供应商兼容接口可用的前提下，可以用于开发者的文本分析、多轮追问和本地知识记录。

本轮基于真实终端使用进一步完成：Windows UTF-8 管道容错、供应商 `finish_reason=length` 检测、ask/chat 截断警告、`Ctrl+C`/EOF 无 traceback 退出，以及笔记 add/delete 持久化失败时的内存回滚语义。
