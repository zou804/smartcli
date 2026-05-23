import argparse
from .config import AVAILABLE_MODELS


def main() -> None:
    parser = argparse.ArgumentParser(prog="smartcli", description="个人智能命令行助手")
    subparsers = parser.add_subparsers(dest="command", required=True)

    weather = subparsers.add_parser("weather", help="查询天气")
    weather.add_argument("city", nargs="?", default="广州", help="城市名称")

    note = subparsers.add_parser("note", help="笔记管理")
    note_sub = note.add_subparsers(dest="action", required=True)
    note_add = note_sub.add_parser("add", help="添加笔记")
    note_add.add_argument("content", help="笔记内容")
    note_sub.add_parser("list", help="查看笔记")
    note_search = note_sub.add_parser("search", help="搜索笔记")
    note_search.add_argument("keyword", help="关键词")

    timer = subparsers.add_parser("timer", help="番茄钟")
    timer.add_argument("minutes", type=int, help="分钟数")

    ask = subparsers.add_parser("ask", help="AI问答")
    ask.add_argument("question", nargs="?", help="问题")
    ask.add_argument("--role", "-r", default="default", choices=["default", "code", "translate", "summary"], help="AI角色")
    ask.add_argument("--model", "-m", default="deepseek-v4", choices=AVAILABLE_MODELS.keys(), help="选择模型")
    ask.add_argument("--chat", action="store_true", help="进入对话模式")


    args = parser.parse_args()

    if args.command == "weather":
        from .commands.weather import handle_weather

        handle_weather(args.city)
    elif args.command == "note":
        from .commands.note import handle_note

        handle_note(args)
    elif args.command == "timer":
        from .commands.timer import handle_timer


    elif args.command == "ask":
        from .commands.ask import handle_ask, handle_chat
        if args.chat:
            handle_chat(model=args.model)
        elif args.question:
            handle_ask(args.question, args.role, args.model)
        else:
            print("请输入问题或使用 --chat 进入对话模式")


if __name__ == "__main__":
    main()
