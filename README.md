# SmartCLI

个人智能命令行助手，提供天气查询、笔记管理、番茄钟和 AI 问答等实用功能。

## 功能特性

- 🌤️ **天气查询** - 支持国内城市天气查询，带缓存机制避免重复请求
- 📝 **笔记管理** - 支持添加、列表、搜索笔记功能
- 🍅 **番茄钟** - 专注计时器，支持自定义时长
- ⚡ **异常处理** - 网络请求自动重试机制
- 🤖 **AI 问答** - 基于 DeepSeek 大模型的智能问答和对话功能

## 技术栈

- **Python 3.11+** - 编程语言
- **argparse** - 命令行参数解析
- **urllib** - HTTP 请求处理
- **dataclasses** - 数据模型定义
- **openai** - AI 模型 API 调用
- **python-dotenv** - 环境变量管理

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/zou804/smartcli.git
cd smartcli
```

### 2. 创建虚拟环境

```bash
# 使用 venv
python -m venv .venv

# 激活虚拟环境
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 开发模式安装（可选）

```bash
pip install -e .
```

### 5. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# DeepSeek API Key（用于 AI 问答功能）
DEEPSEEK_API_KEY=your_api_key_here
```

## 快速开始

### 基础命令

```bash
# 查看帮助
python -m smartcli.cli --help

# 查看子命令帮助
python -m smartcli.cli note --help
```

### 笔记管理

```bash
# 添加笔记
python -m smartcli.cli note add "学习 Python 装饰器"

# 查看所有笔记
python -m smartcli.cli note list

# 搜索笔记
python -m smartcli.cli note search Python
```

### 天气查询

```bash
# 查询指定城市天气
python -m smartcli.cli weather 广州

# 默认查询广州天气
python -m smartcli.cli weather
```

### 番茄钟

```bash
# 启动 25 分钟番茄钟
python -m smartcli.cli timer 25

# 启动 5 分钟休息
python -m smartcli.cli timer 5
```

### AI 问答

```bash
# 单次问答（默认角色）
python -m smartcli.cli ask "Python 装饰器是什么？"

# 指定角色问答
python -m smartcli.cli ask "快速排序怎么写？" -r code
python -m smartcli.cli ask "Hello world" -r translate
python -m smartcli.cli ask "长篇文章内容..." -r summary

# 进入对话模式
python -m smartcli.cli ask --chat
```

**可用角色：**
| 角色 | 说明 |
|------|------|
| `default` | 默认助手 |
| `code` | 代码助手（擅长编程和代码示例） |
| `translate` | 翻译助手 |
| `summary` | 总结助手 |

## 项目结构

```
smartcli/
├── src/
│   └── smartcli/
│       ├── __init__.py
│       ├── cli.py              # 命令行入口
│       ├── commands/           # 命令处理模块
│       │   ├── __init__.py
│       │   ├── ask.py          # AI 问答命令
│       │   ├── note.py         # 笔记管理命令
│       │   ├── timer.py        # 番茄钟命令
│       │   └── weather.py      # 天气查询命令
│       ├── services/           # 服务层
│       │   ├── __init__.py
│       │   ├── llm.py          # 大模型服务
│       │   └── prompts.py      # Prompt 模板
│       └── utils/              # 工具函数
│           ├── __init__.py
│           └── cache.py        # 缓存工具
├── data/                       # 数据文件（自动创建）
│   ├── notes.json              # 笔记数据
│   └── cache.json              # 天气缓存
├── .env                        # 环境变量（需自行创建）
├── .gitignore
├── requirements.txt            # 依赖列表
└── README.md
```

## 数据文件

| 文件 | 说明 | 位置 |
|------|------|------|
| `notes.json` | 笔记数据存储 | `data/notes.json` |
| `cache.json` | 天气缓存数据 | `data/cache.json` |

## 常见问题

### Q: 出现 "ModuleNotFoundError: No module named 'smartcli'"

**原因**：Python 无法找到 `smartcli` 模块

**解决方案**：

方法一：设置 PYTHONPATH

```powershell
# PowerShell
$env:PYTHONPATH = "src"
python -m smartcli.cli note list
```

```bash
# Bash
export PYTHONPATH=src
python -m smartcli.cli note list
```

方法二：开发模式安装

```bash
pip install -e .
```

### Q: AI 问答功能报错

**检查项**：
1. 确认 `.env` 文件中配置了正确的 `DEEPSEEK_API_KEY`
2. 确认网络连接正常
3. 确认 API Key 有足够的余额

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！