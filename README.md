# SmartCLI

## 项目简介

个人智能命令行助手，提供天气查询、笔记管理和番茄钟等实用功能。

## 当前版本

v0.1.0 - 基础功能（天气、笔记、番茄钟）

## 技术栈

- Python 3.11
- argparse（命令行）
- urllib（HTTP 请求，当前无第三方依赖）
- dataclass（数据模型）

## 功能特性

- 🌤️ 天气查询（带缓存）
- 📝 笔记管理（增查搜）
- 🍅 番茄钟计时器
- ⚡ 异常处理与重试机制

## 快速开始

在项目根目录运行：

```bash
python -m smartcli.cli note list
python -m smartcli.cli note add "今天开始开发 SmartCLI"
python -m smartcli.cli note search SmartCLI
python -m smartcli.cli timer 25
python -m smartcli.cli weather 广州
```

如果使用 `src` 布局且尚未安装项目，请先设置 `PYTHONPATH`。

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m smartcli.cli note list
```

Bash:

```bash
export PYTHONPATH=src
python -m smartcli.cli note list
```

也可以直接运行笔记模块：

```bash
python src/smartcli/commands/note.py list
```

## 数据文件

- 笔记默认保存到 `data/notes.json`
- 天气缓存默认保存到 `data/cache.json`

## 命令说明

### 笔记

```bash
python -m smartcli.cli note add "一条新笔记"
python -m smartcli.cli note list
python -m smartcli.cli note search 关键词
```

### 天气

```bash
python -m smartcli.cli weather 广州
```

### 番茄钟

```bash
python -m smartcli.cli timer 25
```

## 常见问题

### attempted relative import with no known parent package

不要直接运行包内模块，例如：

```bash
python src/smartcli/commands/weather.py
```

推荐从项目根目录使用模块方式运行：

```bash
python -m smartcli.cli weather 广州
```
