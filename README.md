# SmartCLI

一个智能命令行工具，支持多模型切换，提供 AI 问答、天气查询、笔记记录等功能。

## 功能特性

- **AI 问答**：支持多种大模型，可切换不同角色（默认、代码助手、总结器）
- **天气查询**：快速获取天气信息
- **笔记记录**：记录和管理笔记
- **计时器**：简单易用的倒计时功能

## 支持的模型

| 模型名 | 提供商 | 说明 |
|--------|--------|------|
| `deepseek-v4` | DeepSeek | 高质量模型（默认） |
| `deepseek-flash` | DeepSeek | 快速响应模型 |

## 安装

```bash
# 克隆项目
git clone <your-repo-url>
cd smartcli

# 创建虚拟环境
python -m venv smartcli
source smartcli/bin/activate  # Linux/Mac
# 或
smartcli\Scripts\activate    # Windows

# 安装依赖
pip install -e .
```

## 配置

创建 `.env` 文件：

```env
# DeepSeek API Key
DEEPSEEK_API_KEY=your-deepseek-api-key
```

## 使用方法

### AI 问答

```bash
# 基本使用
python -m smartcli.cli ask "你的问题"

# 指定角色
python -m smartcli.cli ask "快速排序怎么写？" -r code

# 指定模型
python -m smartcli.cli ask "你好" -m deepseek-v4
python -m smartcli.cli ask "你好" -m deepseek-flash
```

### 可用角色

| 参数 | 角色 | 说明 |
|------|------|------|
| `-r default` | 默认 | 友好的通用助手 |
| `-r code` | 代码助手 | 专业的编程助手 |
| `-r summary` | 总结器 | 文本摘要助手 |

### 其他功能

```bash
# 天气查询
python -m smartcli.cli weather 北京

# 笔记记录
python -m smartcli.cli note add "学习笔记" "今天学习了Python装饰器"

# 查看笔记列表
python -m smartcli.cli note list

# 计时器
python -m smartcli.cli timer 5
```

## 项目结构

```
smartcli/
├── src/
│   └── smartcli/
│       ├── __init__.py
│       ├── cli.py              # 命令行入口
│       ├── config.py           # 模型配置
│       ├── commands/           # 命令实现
│       │   ├── __init__.py
│       │   ├── ask.py          # AI问答命令
│       │   ├── weather.py      # 天气命令
│       │   ├── note.py         # 笔记命令
│       │   └── timer.py        # 计时器命令
│       └── services/           # 服务层
│           ├── __init__.py
│           ├── llm.py          # 大模型服务
│           └── prompts.py      # 提示词模板
├── .env                        # 环境变量
├── .gitignore                  # Git忽略文件
├── pyproject.toml              # 项目配置
└── README.md                   # 项目说明
```

## 技术栈

- Python 3.8+
- argparse - 命令行解析
- OpenAI SDK - API 调用
- python-dotenv - 环境变量管理

## 许可证

MIT License
